import os
import numpy as np
import tensorflow as tf
from io import StringIO

class KerasLMSentenceLevelBatchGenerator(object):
    """ Adapted from http://adventuresinmachinelearning.com/keras-lstm-tutorial/
    
        Does not use continous / running text as the original implementation, but rather
        text that has been sentence-tokenized in advance.
    
        Given:
        [['<pad>', '<pad>', '<s>', 'The', 'cat', 'sat', 'on', 'a', 'mat', 'and', 'ate', 'his', 'hat', '.', '<eos>']]
    
        and: skip_steps=1
    
        Yield:
        [
            ['<pad>', '<pad>', '<s>', 'The', 'cat'],
            ['<pad>', '<s>', 'The', 'cat', 'sat'],
            ['<s>', 'The', 'cat', 'sat', 'on'],
            ['The', 'cat', 'sat', 'on', 'a'],
            ['cat', 'sat', 'on', 'a', 'mat'],
            ['on', 'a', 'mat', 'and', 'ate'],
            ['a', 'mat', 'and', 'ate', 'his'],
            ['mat', 'and', 'ate', 'his', 'hat'],
            ['and', 'ate', 'his', 'hat', '.'],
        ],
        [
            ['<pad>', '<s>', 'The', 'cat', 'sat'],
            ['<s>', 'The', 'cat', 'sat', 'on'],
            ['The', 'cat', 'sat', 'on', 'a'],
            ['cat', 'sat', 'on', 'a', 'mat'],
            ['on', 'a', 'mat', 'and', 'ate'],
            ['a', 'mat', 'and', 'ate', 'his'],
            ['mat', 'and', 'ate', 'his', 'hat'],
            ['and', 'ate', 'his', 'hat', '.'],
            ['ate', 'his', 'hat', '.', '<eos>'],
        ],
    
    
        We expect x_sequences to be padded, but they don't need to be arrays of strings. In fact, it's
        more likely that we will see arrays of indices.
    """

    def __init__(self, *, x_sequences, max_seq_len, min_seq_len, num_shifted_sentences, pad_idx_or_symbol, skip_step=5, explicit_x_seq_len=None, no_slurp=False):
        if skip_step > max_seq_len:
            raise ValueError("Skip step needs to be greater than or equal to the max sequence length")
        self.x_sequences = x_sequences
        self.explicit_seq_len = explicit_x_seq_len or len(x_sequences)
        self.no_slurp = no_slurp
        self.max_seq_len = max_seq_len
        self.min_seq_len = min_seq_len
        self.num_shifted_sentences = num_shifted_sentences
        # self.vocabulary = vocabulary
        # this will track the progress of the batches sequentially through the
        # data set - once the data reaches the end of the data set it will reset
        # back to zero
        self.current_idx = 0
        # skip_step is the number of words which will be skipped before the next
        # batch is skimmed from the data set
        self.skip_step = skip_step
        self.pad_idx_or_symbol = pad_idx_or_symbol

    def get_num_sliding_windows(self):
        return self.max_seq_len // self.skip_step # each batch will generate num_shifted_sentences * num_sliding_windows examples

    def get_batch_size(self):
        return self.num_shifted_sentences*self.get_num_sliding_windows()

    def get_epoch_size(self):
        return self.explicit_seq_len*self.get_num_sliding_windows()

    def get_steps_per_epoch(self):
        return self.get_epoch_size() // self.get_batch_size()

    def print_batch_info(self, batch_size=None):
        cols = "{0:8}{1:40}{2:6}"
        print("******************** BATCH GENERATION SUMMARY **************************")
        print(cols.format("  (1)", "Total # of sentences;", self.explicit_seq_len))
        print(cols.format("  (2)", "Max sequence length", self.max_seq_len))
        print(cols.format("  (3)", "Skip step", self.skip_step))
        print(cols.format("  (4)", "# of sliding windows per sentence", self.get_num_sliding_windows()))
        print(cols.format("  (5)", "# sentences to shift in each batch", self.num_shifted_sentences))
        print(cols.format("  (6)", "# of examples per epoch", self.get_epoch_size()))
        print(cols.format("  (7)", "Batch size", self.get_batch_size()))
        print(cols.format("  (8)", "# of steps per epoch", self.get_steps_per_epoch()))
        print("************************************************************************")

    def generate(self):
        return self.generate_from_disk() if self.no_slurp else self.generate_slurped()

    def generate_slurped(self):
        num_sliding_windows = self.max_seq_len // self.skip_step # each batch will generate num_shifted_sentences * num_sliding_windows examples
        print(f"SLURP / Number of sliding windows: {num_sliding_windows}")
        print(f"SLURP / Expected number of rows in shifted x_sequences: {num_sliding_windows*self.num_shifted_sentences}")

        while True:
            if self.current_idx + self.num_shifted_sentences >= self.explicit_seq_len:
                # reset the index back to the start of the data set
                self.current_idx = 0
            x = []
            y = []

            for window_idx in range(num_sliding_windows): # shift the sequence *to the left* by `skip_step` tokens
                x_shifted = self.x_sequences[self.current_idx:self.current_idx+self.num_shifted_sentences][:,window_idx*self.skip_step:]
                x.extend(x_shifted)
                y.extend(x_shifted[:, 1:])
            self.current_idx += self.num_shifted_sentences
            x = tf.keras.preprocessing.sequence.pad_sequences(x, maxlen=self.max_seq_len, value=1, padding="post")
            y = tf.keras.preprocessing.sequence.pad_sequences(y, maxlen=self.max_seq_len, value=1, padding="post")
            yield x, y

    def generate_from_disk(self):
        num_sliding_windows = self.max_seq_len // self.skip_step # each batch will generate num_shifted_sentences * num_sliding_windows examples
        print(f"DISK / Number of sliding windows: {num_sliding_windows}")
        print(f"DISK / Expected number of rows in shifted x_sequences: {num_sliding_windows*self.num_shifted_sentences}")
        fsize = os.path.getsize(self.x_sequences)
        fd = open(self.x_sequences, 'r', encoding='utf-8')
        while True:
            x_local_sequences = []
            cnt = 0
            #for i in range(self.num_shifted_sentences):
            while True:
                if fd.tell() > fsize: fd.seek(0)
                line = np.genfromtxt(StringIO(fd.readline()), dtype=int)
                if len(line) < self.min_seq_len: continue
                if len(line) > self.max_seq_len: line[self.max_seq_len-1] = 3
                x_local_sequences.append(line)
                cnt += 1
                if cnt >= self.num_shifted_sentences: break
            x_local_sequences = tf.keras.preprocessing.sequence.pad_sequences(x_local_sequences, \
                                                                              padding='post', truncating='post',\
                                                                              maxlen=self.max_seq_len, \
                                                                              value=self.pad_idx_or_symbol)
            x = []
            y = []

            for window_idx in range(num_sliding_windows): # shift the sequence *to the left* by `skip_step` tokens
                x_shifted = x_local_sequences[:][:,window_idx*self.skip_step:]
                x.extend(x_shifted)
                y.extend(x_shifted[:, 1:])
            x = tf.keras.preprocessing.sequence.pad_sequences(x, maxlen=self.max_seq_len, value=1, padding="post")
            y = tf.keras.preprocessing.sequence.pad_sequences(y, maxlen=self.max_seq_len, value=1, padding="post")
            yield x, y

    def reset(self):
        self.current_idx = 0