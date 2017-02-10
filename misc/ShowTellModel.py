from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.autograd import *
import misc.utils as utils

MAX_STEPS = 30

class ShowTellModel(nn.Module):
    def __init__(self, opt):
        super(ShowTellModel, self).__init__()
        self.vocab_size = opt.vocab_size
        self.input_encoding_size = opt.input_encoding_size
        self.rnn_type = opt.rnn_type
        self.rnn_size = opt.rnn_size
        self.num_layers = opt.num_layers
        self.drop_prob_lm = opt.drop_prob_lm
        self.seq_length = opt.seq_length
        self.fc_feat_size = opt.fc_feat_size

        self.ss_prob = 0.0 # Schedule sampling probability

        self.img_embed = nn.Linear(self.fc_feat_size, self.input_encoding_size)
        self.core = getattr(nn, self.rnn_type.upper())(self.input_encoding_size, self.rnn_size, self.num_layers, bias=False)
        self.embed = nn.Embedding(self.vocab_size + 1, self.input_encoding_size)
        self.logit = nn.Linear(self.rnn_size, self.vocab_size + 1)

        self.init_weights()

    def init_weights(self):
        initrange = 0.1
        self.embed.weight.data.uniform_(-initrange, initrange)
        self.logit.bias.data.fill_(0)
        self.logit.weight.data.uniform_(-initrange, initrange)

    def init_hidden(self, bsz):
        weight = next(self.parameters()).data
        if self.rnn_type == 'lstm':
            return (Variable(weight.new(self.num_layers, bsz, self.rnn_size).zero_()),
                    Variable(weight.new(self.num_layers, bsz, self.rnn_size).zero_()))
        else:
            return Variable(weight.new(self.num_layers, bsz, self.rnn_size).zero_())

    def forward(self, fc_feat, att_feat, seq):
        batch_size = fc_feat.size(0)
        state = self.init_hidden(batch_size)
        outputs = []

        for i in range(seq.size(1)):
            if i == 0:
                xt = self.img_embed(fc_feat)
            else:
                if i >= 2 and self.ss_prob > 0.0: # otherwiste no need to sample
                    sample_prob = fc_feat.data.new(batch_size).uniform_(0, 1)
                    sample_mask = sample_prob < self.ss_prob
                    if sample_mask.sum() == 0:
                        it = seq[:, i-1].clone()
                    else:
                        sample_ind = sample_mask.nonzero().view(-1)
                        it = seq[:, i-1].data.clone()
                        #prob_prev = torch.exp(outputs[-1].data.index_select(0, sample_ind)) # fetch prev distribution: shape Nx(M+1)
                        #it.index_copy_(0, sample_ind, torch.multinomial(prob_prev, 1).view(-1))
                        prob_prev = torch.exp(outputs[-1].data) # fetch prev distribution: shape Nx(M+1)
                        it.index_copy_(0, sample_ind, torch.multinomial(prob_prev, 1).view(-1).index_select(0, sample_ind))
                        it = Variable(it)
                else:
                    it = seq[:, i-1].clone()
                xt = self.embed(it)

            output, state = self.core(xt.unsqueeze(0), state)
            output = F.log_softmax(self.logit(output.squeeze(0)))
            outputs.append(output)

        return torch.cat([_.unsqueeze(1) for _ in outputs], 1).contiguous()

    def sample_beam(self, fc_feat, att_feat, opt):
        return None

    def sample(self, fc_feat, att_feat, opt):
        sample_max = opt.get('sample_max', True)
        beam_size = opt.get('beam_size', 1)
        temperature = opt.get('sample_temperature', 1.0)
        if sample_max == True and beam_size > 1:
            return self.sample_beam(fc_feat, att_feat, opt)

        batch_size = fc_feat.size(0)
        state = self.init_hidden(batch_size)
        seq = []
        seqLogprobs = []
        for t in range(MAX_STEPS):
            if t == 0:
                xt = self.img_embed(fc_feat)
            else:
                if sample_max:
                    sampleLogprobs, it = torch.max(logprobs.data, 1)
                    it = it.view(-1).long()
                else:
                    if temperature == 1.0:
                        prob_prev = torch.exp(logprobs.data).cpu() # fetch prev distribution: shape Nx(M+1)
                    else:
                        # scale logprobs by temperature
                        prob_prev = torch.exp(torch.div(logprobs.data, temperature)).cpu()
                    it = torch.multinomial(prob_prev, 1).cuda()
                    sampleLogprobs = logprobs.gather(1, it) # gather the logprobs at sampled positions
                    it = it.view(-1).long() # and flatten indices for downstream processing

                xt = self.embed(Variable(it))

            if t >= 2:
                seq.append(it)
                seqLogprobs.append(sampleLogprobs.view(-1))

            output, state = self.core(xt.unsqueeze(0), state)
            logprobs = F.log_softmax(self.logit(output.squeeze(0)))

        return torch.cat([_.unsqueeze(1) for _ in seq], 1), torch.cat([_.unsqueeze(1) for _ in seqLogprobs], 1)

# class ShowAttendTell(nn.Module):
#     def __init__(self, opt):
#         super(LanguageModel, self).__init__()

#         self.vocab_size = opt.vocab_size
#         self.input_encoding_size = opt.input_encoding_size
#         self.rnn_size = opt.rnn_size
#         self.num_layers = opt.num_layers
#         self.drop_prob_lm = opt.drop_prob_lm
#         self.seq_length = opt.seq_length
#         self.att_hid_size = opt.att_hid_size
#         self.att_feat_size = opt.att_feat_size
#         self.fc_feat_size = opt.fc_feat_size
#         self.rnn = RNNModel()
#         if self.att_hid_size == 0:
#             self.ctx_att = nn.Linear(self.att_feat_size, self.att_hid_size)
#         else:
#             self.ctx_att = nn.Linear(self.att_feat_size, 1)
        

#     def forward(self, fc_feat, att_feat, labels):
#         batch_size = fc_feat.size(0)
#         flattened_ctx = att_feat.view(batch_size, att_feat.size(1)*att_feat.size(2),att_feat.size(3))
#         ctx_mean = att_feat.mean(1).squeeze(1)

#         initial_state = self.rnn.init_hidden(batch_size)
#         pctx = self.ctx_att(self.flattened_ctx)

#         for i in range(labels.size(1)):
#             l = label[:,i]






