# ******************************************************************************
# Copyright 2017-2018 Intel Corporation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ******************************************************************************
from ngraph.util.persist import valid_path_append, fetch_file
import os
import numpy as np


class PTB(object):
    """
    Penn Treebank data set from http://arxiv.org/pdf/1409.2329v5.pdf

    Arguments:
        path (string): Data directory to find the data, if not existing, will
                       download the data
        shift_target (boolean): Set the target to be the same sequence of shifted
                                version of the sequence. Default to be True, for
                                language models.
    """
    def __init__(self, path='.', use_words=False, shift_target=True):
        self.path = path
        self.url = 'https://raw.githubusercontent.com/wojzaremba/lstm/master/data'
        self.filemap = dict(train=dict(filename='ptb.train.txt', size=5101618),
                            test=dict(filename='ptb.test.txt', size=449945),
                            valid=dict(filename='ptb.valid.txt', size=399782))
        self.shift_target = shift_target
        self.use_words = use_words

    def load_data(self):
        self.data_dict = {}
        self.vocab = None
        for phase in ['train', 'test', 'valid']:
            filename, filesize = self.filemap[phase]['filename'], self.filemap[phase]['size']
            workdir, filepath = valid_path_append(self.path, '', filename)
            if not os.path.exists(filepath):
                fetch_file(self.url, filename, filepath, filesize)

            tokens = open(filepath).read()  # add tokenization here if necessary

            if self.use_words:
                tokens = tokens.strip().split()

            self.vocab = sorted(set(tokens)) if self.vocab is None else self.vocab

            # vocab dicts
            self.token_to_index = dict((t, i) for i, t in enumerate(self.vocab))
            self.index_to_token = dict((i, t) for i, t in enumerate(self.vocab))

            # map tokens to indices
            X = np.asarray([self.token_to_index[t] for t in tokens], dtype=np.uint32)
            if self.shift_target:
                y = np.concatenate((X[1:], X[:1]))
            else:
                y = X.copy()

            self.data_dict[phase] = {'inp_txt': X, 'tgt_txt': y}

        return self.data_dict
