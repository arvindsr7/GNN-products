import torch
import torch_scatter
import torch.nn as nn
import torch.nn.functional as F
import torch_geometric.utils as pyg_utils
from torch_geometric.nn.conv import MessagePassing
from objectview import objectview


class ResNetBlock(torch.nn.Module):
    def __init__(self, module):
        super(ResNetBlock, self).__init__()
        self.module = module

    def forward(self, inputs):
        return self.module(inputs) + inputs

    def reset_parameters(self):
        for l in self.module:
            l.reset_parameters()


class ResNetPostMP(torch.nn.Module):
    def __init__(self, input_dim, hidden_dim, output_dim, arg, emb=False):
        super(ResNetPostMP, self).__init__()
        args = objectview(arg)
        conv_model = GraphSage
        self.post_hidden = args.post_hidden
        post_hidden = self.post_hidden

        self.convs = nn.ModuleList()
        self.affine = nn.Linear(input_dim, hidden_dim)
        for l in range(args.num_layers):
            self.convs.append(conv_model(hidden_dim, hidden_dim))

        self.bns = torch.nn.ModuleList([torch.nn.BatchNorm1d(hidden_dim)
                                        for _ in range(args.num_layers)])

        # self.post_mp = nn.Sequential(
        #     nn.Linear(hidden_dim, hidden_dim),
        #     nn.Dropout(args.dropout),
        #     nn.Linear(hidden_dim, output_dim))

        # post-message-passing
        # TODO: Make module list
        self.post_mp = nn.Sequential(
            ResNetBlock(
                nn.Sequential(
                    nn.Linear(post_hidden, post_hidden),
                    nn.ReLU(),
                    nn.BatchNorm1d(post_hidden),
                )),
            nn.Dropout(args.dropout),
            nn.Linear(post_hidden, output_dim)
        )

        self.dropout = args.dropout
        self.num_layers = args.num_layers

        self.emb = emb

    def forward(self, x, edge_index):

        x = self.affine(x)
        x = F.relu(x)

        res = self.convs[0](x, edge_index)

        for i in range(1, self.num_layers):
            x = self.bns[i-1](res)
            x = F.relu(x)
            x = F.dropout(x, p=self.dropout)
            res = self.convs[i](x, edge_index) + res

        x = self.bns[-1](res)
        x = F.relu(x)
        x = F.dropout(x, p=self.dropout)

        x = self.post_mp(x + res)

        if self.emb:
            return x

        return F.log_softmax(x, dim=1)

    def loss(self, pred, label):
        return F.nll_loss(pred, label)

    def reset_parameters(self):
        for c in self.convs:
            c.reset_parameters()


class GraphSage(MessagePassing):
    def __init__(self, in_channels, out_channels, normalize=True, bias=False, **kwargs):
        super(GraphSage, self).__init__(**kwargs)

        self.in_channels = in_channels
        self.out_channels = out_channels
        self.normalize = normalize

        self.lin_l = nn.Linear(in_channels, out_channels)
        self.lin_r = nn.Linear(in_channels, out_channels)

        self.reset_parameters()

    def reset_parameters(self):
        self.lin_l.reset_parameters()
        self.lin_r.reset_parameters()

    def forward(self, x, edge_index, size=None):

        z = self.propagate(edge_index, x=(x, x), dim_size=x.shape)
        out = self.lin_l(x) + self.lin_r(z)
        if self.normalize:
            out = F.normalize(out)
        return out

    def message(self, x_j):
        return x_j

    def aggregate(self, inputs, index, dim_size=None):

        # The axis along which to index number of nodes.
        node_dim = self.node_dim
        out = torch_scatter.scatter(inputs, index=index, dim=node_dim, reduce='mean', dim_size=dim_size)

        return out
