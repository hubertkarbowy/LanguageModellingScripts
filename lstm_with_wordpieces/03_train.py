import os, subprocess, argparse
import logging
import pickle
import tensorflow as tf
import numpy as np
import sentencepiece as spm
from lm_keras_generators import KerasLMSentenceLevelBatchGenerator

"""
Train an LSTM-based language model on texts pretokenized with SPM.

Sample usage:

python 03_train.py --corpus-path /wymiana/Projekty/NLP/NlpMementos_data/word_vectors/../datasets/books/therepublic_pretokenized.txt \
                   --spm-model-file ./plato-sp5k.model \
                   --max-seq-len 40 \
                   --add-bos \
                   --add-eos \
                   --num-sents-to-shift 8 \
                   --num-epochs 40
"""

# todo: migrate spmto tensorflow_text?
UNK_ID=0; PAD_ID=1; BOS_ID=2; EOS_ID=3
logging.basicConfig(level=logging.INFO)

def get_spm_extra_opts(args):
    extra_opts=[]
    if args.get('add_bos') is True:
        extra_opts.append("bos")
    if args.get('add_eos') is True:
        extra_opts.append("eos")
    return ":".join(extra_opts)

def prepare_sequences(spmproc, args):
    x_sequences = []
    cnt = 0
    with open(args['corpus_path'], 'r', encoding='utf-8') as f:
        for line in f:
            if cnt % 100000 == 0: logging.info(f"Processing line {cnt}")
            pieces = spmproc.encode_as_ids(line)
            if len(pieces) < args['min_seq_len']: continue
            if len(pieces) > args['max_seq_len']:
                pieces = pieces[0:args['max_seq_len']]
                if args['add_eos'] is True: pieces[-1] = 3 # fixme: this is hardcoded - not good!
            x_sequences.append(pieces)
            cnt += 1

    logging.info("Tokenization completed. First 10 sentences:")
    for i in range(10):
        pieces = [spmproc.id_to_piece(x) for x in x_sequences[i]]
        logging.info(str(pieces))
    x_sequences = tf.keras.preprocessing.sequence.pad_sequences(x_sequences, \
                                                                padding=args['padding_direction'], \
                                                                maxlen=args['max_seq_len'], \
                                                                value=PAD_ID)
    return x_sequences

def build_keras_model(spmproc, args):
    model = tf.keras.models.Sequential()
    model.add(tf.keras.layers.Masking(mask_value=1, input_shape=(args['max_seq_len'], )))
    model.add(tf.keras.layers.Embedding(spmproc.vocab_size(), 256,
              input_length=args['max_seq_len']))   # FIXME: create a custom masking layer that uses 1, not 0 as padding
    model.add(tf.keras.layers.LSTM(256, return_sequences=True))
    model.add(tf.keras.layers.Dropout(0.5))
    model.add(tf.keras.layers.LSTM(256, return_sequences=True))
    model.add(tf.keras.layers.Dropout(0.5))
    model.add(tf.keras.layers.TimeDistributed(
                              tf.keras.layers.Dense(spmproc.vocab_size(), activation='softmax')))
    model.compile(loss='sparse_categorical_crossentropy', optimizer='adam', metrics=['sparse_categorical_accuracy'])
    return model

def main(args):
    spmproc = spm.SentencePieceProcessor(args['spm_model_file'])
    spmproc.SetEncodeExtraOptions(get_spm_extra_opts(args))
    logging.info(f"SPM processor detected vocab size of {spmproc.vocab_size}. First 10 tokens:")    
    logging.info(str([spmproc.id_to_piece(i) for i in range(10)]))
    logging.info(f"Running tokenization and padding...")    
    # x_sequences = args['corpus_path'] if args['no_slurp'] is True else prepare_sequences(spmproc, args)
    if args['no_slurp'] is True:
        x_sequences = args['corpus_path']
        explicit_x_seq_len = int(subprocess.check_output(['wc', '-l', args['corpus_path']]).split()[0])
    else:
        x_sequences = prepare_sequences(spmproc, args)
        explicit_x_seq_len = None
    batch_generator = KerasLMSentenceLevelBatchGenerator(x_sequences=x_sequences, \
                                                         max_seq_len=args['max_seq_len'], 
                                                         min_seq_len=args['min_seq_len'],\
                                                         num_shifted_sentences=args.get('num_sents_to_shift') or 3,
                                                         pad_idx_or_symbol=PAD_ID,
                                                         skip_step=args.get('skip_step') or 5,
                                                         explicit_x_seq_len=explicit_x_seq_len,
                                                         no_slurp=args['no_slurp'])
    batch_generator.print_batch_info()
    simple_model = build_keras_model(spmproc, args)
    #checkpointer = tf.keras.callbacks.ModelCheckpoint(filepath=os.path.join(args['ckpt_path'], f"{args['exp_name']}-{epoch:02d}.hdf5"), verbose=1)
    checkpointer = tf.keras.callbacks.ModelCheckpoint(filepath=args['ckpt_path']+"/"+args['exp_name']+"-{epoch:02d}.hdf5", verbose=1)
    simple_model.summary()
    # simple_model.load_weights("./model-06.hdf5")
    simple_model.fit(batch_generator.generate(), \
                     steps_per_epoch=batch_generator.get_steps_per_epoch(), \
                     epochs=args['num_epochs'],
                     callbacks=[checkpointer]
                    )

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus-path", required=True, help="Path to a raw text corpus. One big single file. One line = one sentence.")
    parser.add_argument("--no-slurp", required=False, action='store_true', help="If set to true, the following is assumed: 1) input file contains preprocessed, pretokenized text coverted to SPM ids, 2) one encoded sentence = one line. Use this if your input is gigantic and you don't want to slurp everything to memory.")
    parser.add_argument("--feed-method", choices=['sentence_tokenized', 'running_text'], default="sentence_tokenized")
    parser.add_argument("--spm-model-file", required=True, help="SPM .model file")
    parser.add_argument("--add-bos", required=False, action='store_true', help="Will add <s> tokens")
    parser.add_argument("--add-eos", required=False, action='store_true', help="Will add </s> tokens")
    parser.add_argument("--min-seq-len", required=False, type=int, default=15, help="Minimum number of wordpiece tokens in a sequence")
    parser.add_argument("--max-seq-len", required=True, type=int, help="Maximum number of wordpiece tokens in a sequence")
    parser.add_argument("--padding-direction", choices=['pre', 'post'], default='post', help="Pre or post padding (for LM training 'post' seems better than 'pre')")
    parser.add_argument("--num-sents-to-shift", type=int, default=3, help= \
                        "Number of sentences to use for left shifts in each batch. THIS PARAMETER CONTROLS THE BATCH SIZE ACCORDING TO THE FORMULA: "\
                        "batch-size = num-sents-to-shift * (max-seq-len // skip-step) ")
    parser.add_argument("--skip-step", type=int, default=5, help="Number of tokens by which to shift all sequences in a batch to the left")
    parser.add_argument("--num-epochs", type=int, default=10, help="Number of epochs to train for")
    parser.add_argument("--ckpt-path", default=".", help="Where to strore trained checkpoints")
    parser.add_argument("--exp-name", required=True, help="Experiment name")
    argz = parser.parse_args()
    main(vars(argz))