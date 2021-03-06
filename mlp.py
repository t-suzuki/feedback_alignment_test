#!env python
# -*- coding: utf-8 -*-
# test various learning methods:
# BP: back propagation
# PI: pseudoinverse
# FA: feedback alignment
# FA-PI-W: feedback alignment initialized B from random W
# FA-PI-B: feedback alignment initialized W from random B
import argparse
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import sklearn.datasets
import sklearn.cross_validation

## activations.
# note: dXXX functions are defined to hold df(z = f(y)) = d(f(y))/dy but not df(y) = d(f(y))/dy
def sigmoid(y): return 1.0 / (1.0 + np.exp(-y))
def dsigmoid(z): return z * (1.0 - z)
def tanh(y): return np.tanh(y)
def dtanh(z): return 1.0 - z**2.0
def relu(y): return np.maximum(0, y)
def drelu(z): return (z > 0) * 1.0
def identity(y): return y
def didentity(z): return 1.0
activation_funcs = {
        'sigmoid': (sigmoid, dsigmoid),
        'tanh': (tanh, dtanh),
        'relu': (relu, drelu),
        'identity': (identity, didentity),
        }

## loss functions
def mse_loss(y_pred, y_true): return 0.5 * (y_pred -  y_true)**2
def mse_loss_prime(y_pred, y_true): return y_pred -  y_true
def softmax(y):
    ey = np.exp(y)
    return ey / ey.sum(axis=1)[:, np.newaxis]
def softmax_cross_entropy_loss(y_pred, y_true):
    p_pred = softmax(y_pred)
    p_true = y_true
    return (- p_true * np.log(p_pred) - (1.0 - p_true) * np.log(1.0 - p_pred)).sum(axis=1)
def softmax_cross_entropy_loss_prime(y_pred, y_true):
    return softmax(y_pred) - y_true
loss_funcs = {
        'mse': (mse_loss, mse_loss_prime),
        'softmax_cross_entropy': (softmax_cross_entropy_loss, softmax_cross_entropy_loss_prime),
        }

## utility
def normalize_xavier(x, n):
    return x / (np.var(x) * n)

def add_bias(x):
    assert len(x.shape) == 2
    return np.hstack([x, np.ones((x.shape[0], 1))])

def pseudo_inverse(w):
    eps = 1.0e-3 # avoid singular matrix
    if w.shape[0] <= w.shape[1]:
        b = np.dot(w.T, np.linalg.inv(np.dot(w, w.T) + np.eye(w.shape[0]) * eps))
    else:
        b = np.dot(np.linalg.inv(np.dot(w.T, w) + np.eye(w.shape[1]) * eps), w.T)
    #eye = np.dot(w, b)
    #print np.diag(eye)
    return b

class MLP(object):
    def __init__(self, input_dim, layers, loss_type, learning = 'BP', verbose = False):
        self.backward_weights = []
        self.weights = []
        self.updateable = []
        self.funcs = []
        ch_in = input_dim
        for ch_out, activation_type, is_updatable in layers:
            w = np.random.randn(ch_out, ch_in + 1)
            if False:
                n = min(ch_in, ch_out)
                for i in range(n):
                    w[i, i] += 1.0/n
            w = normalize_xavier(w, np.sqrt(ch_out + ch_in))
            if learning == 'BP':
                # ordinary back propagation.
                pass
            elif learning == 'PI':
                # use pseudo inverse of w.
                pass
            elif learning == 'FA':
                # "Random feedback weights support learning in deep neural networks", T.P.Lillicrap+, CoRR 2014.
                w[:, :-1] *= 0 # zero initialize except for the bias.
                b = normalize_xavier(np.random.randn(ch_out, ch_in), ch_out)
                self.backward_weights.append(b)
            elif learning == 'FA-PI-W':
                # Random feedback weights initialized with pseudo inverse pairs. (w determines b)
                b = pseudo_inverse(w[:, :-1]).T
                b = normalize_xavier(b, ch_out)
                self.backward_weights.append(b)
            elif learning == 'FA-PI-B':
                # Random feedback weights initialized with pseudo inverse pairs. (b determines w)
                b = np.random.randn(ch_out, ch_in)
                b = normalize_xavier(b, ch_out)
                w = add_bias(normalize_xavier(pseudo_inverse(b).T, ch_in))
                self.backward_weights.append(b)
            else:
                raise RuntimeError('unknown learning method')
            self.weights.append(w)
            self.updateable.append(is_updatable)
            self.funcs.append(activation_funcs[activation_type])
            ch_in = ch_out
        self.loss = loss_funcs[loss_type]
        self.learning = learning
        self.verbose = verbose

    def forward(self, xs_batch):
        assert len(xs_batch.shape) == 2
        n_batch, n_dim = xs_batch.shape
        self.activations = [xs_batch]
        for i, (w, (f, _)) in enumerate(zip(self.weights, self.funcs)):
            x = self.activations[-1]
            x = add_bias(x)
            z = f(np.dot(x, w.T))
            self.activations.append(z)
            if self.verbose: print 'layer %d. %s -> %s' % (i, x.shape, z.shape)
        return z

    def backward(self, delta, eta, gradient_noise = 0.0):
        deltas = [delta]
        for i, (w, (_, df)) in list(enumerate(zip(self.weights, self.funcs)))[::-1]:
            delta = deltas[-1]
            if self.verbose: print 'calc delta for layer %d. delta %s -> weight %s' % (i, delta.shape, w.shape)
            if self.learning == 'BP':
                transport = w[:, :-1]
            elif self.learning == 'PI':
                transport = pseudo_inverse(w[:, :-1]).T
            elif self.learning in ['FA', 'FA-PI-W', 'FA-PI-B']:
                transport = self.backward_weights[i]
            delta = df(self.activations[i]) * np.dot(delta, transport)
            deltas.append(delta)
        deltas.reverse()

        for i, delta in enumerate(deltas[1:]):
            if self.verbose:
                print 'update layer %d. delta %s, activation %s, weight %s' % (
                        i, delta.shape, self.activations[i].shape, self.weights[i].shape)
            if not self.updateable[i]:
                continue
            x = self.activations[i]
            x = add_bias(x)
            diff = np.dot(delta.T, x)
            if gradient_noise > 0:
                diff += np.random.randn(*diff.shape) * gradient_noise
            self.weights[i] -= eta * diff

    def weight_decay(self, decay):
        for i in range(len(self.weights)):
            # decay weights but not biases
            self.weights[i][:, :-1] *= decay

    def fit(self, xs_train, ys_train, xs_validation = None, ys_validation = None,
            batchsize = 64, n_epoch = 5, learning_rate = 0.001, gradient_noise = 0.0, weight_decay = 0.0):
        assert len(xs_train.shape) == 2
        assert xs_train.shape[0] == ys_train.shape[0]
        N_train = len(ys_train)
        if xs_validation is not None and ys_validation is not None:
            assert len(xs_validation.shape) == 2
            assert xs_validation.shape[0] == ys_validation.shape[0]
            assert xs_train.shape[1] == xs_validation.shape[1]
            N_validation = len(ys_validation)
        else:
            N_validation = 0
        total_samples = 0
        log = []
        try:
            for iepoch in range(n_epoch):
                loss, acc, accum_batch_samples = 0.0, 0.0, 0
                for i in range(0, N_train, batchsize):
                    batchidx = range(i, min(N_train, i + batchsize))
                    xs_batch = xs_train[batchidx]
                    ys_batch = ys_train[batchidx]

                    ps_batch = self.forward(xs_batch)
                    delta = self.loss[1](ps_batch, ys_batch) / float(len(batchidx))
                    loss += self.loss[0](ps_batch, ys_batch).sum()
                    acc += np.count_nonzero(ys_batch.argmax(axis=1) == ps_batch.argmax(axis=1))
                    accum_batch_samples += len(batchidx)
                    log.append(dict(n=total_samples + accum_batch_samples, loss=loss/float(accum_batch_samples), acc=acc/float(accum_batch_samples), type='train-intermediate'))

                    self.backward(delta, learning_rate, gradient_noise)

                    if weight_decay > 0:
                        self.weight_decay((1.0 - weight_decay) ** len(batchidx))

                loss /= float(N_train)
                acc /= float(N_train)
                total_samples += N_train
                log.append(dict(n=total_samples, loss=loss, acc=acc, type='train'))
                print 'epoch %3d/%3d %-12s loss=%f acc=%f' % (iepoch + 1, n_epoch, 'train', loss, acc)

                if N_validation > 0:
                    loss, acc = 0.0, 0.0
                    for i in range(0, N_validation, batchsize):
                        batchidx = range(i, min(N_validation, i + batchsize))
                        xs_batch = xs_validation[batchidx]
                        ys_batch = ys_validation[batchidx]

                        ps_batch = self.forward(xs_batch)
                        loss += self.loss[0](ps_batch, ys_batch).sum()
                        acc += np.count_nonzero(ys_batch.argmax(axis=1) == ps_batch.argmax(axis=1))
                    loss /= float(N_validation)
                    acc /= float(N_validation)
                    log.append(dict(n=total_samples, loss=loss, acc=acc, type='validation'))
                    print 'epoch %3d/%3d %-12s loss=%f acc=%f' % (iepoch + 1, n_epoch, 'validation', loss, acc)
        except KeyboardInterrupt:
            if raw_input('terminate?').lower() == 'y':
                raise
        self.fit_log = pd.DataFrame(log)

    def get_fit_log(self): return self.fit_log

    def predict(self, xs_test, batchsize = 64):
        N_test = xs_test.shape[0]
        ps = []
        for i in range(0, N_test, batchsize):
            batchidx = range(i, min(N_test, i + batchsize))
            ps.append(self.forward(xs_test[batchidx]))
        return np.vstack(ps)

def plot_fit_log(df_log):
    fig, axs = plt.subplots(2, 1)
    df_train = df_log[df_log['type'] == 'train-intermediate']
    if len(df_train) > 0:
        axs[0].plot(df_train['n'], df_train['loss'], '-', alpha=0.5, color='blue')
        axs[1].plot(df_train['n'], df_train['acc'], '-', alpha=0.5, color='blue')

    df_train = df_log[df_log['type'] == 'train']
    if len(df_train) > 0:
        axs[0].plot(df_train['n'], df_train['loss'], 'o-', linewidth=1, color='blue', label='train')
        axs[1].plot(df_train['n'], df_train['acc'], 'o-', linewidth=1, color='blue', label='train')

    df_validation = df_log[df_log['type'] == 'validation']
    if len(df_validation) > 0:
        axs[0].plot(df_validation['n'], df_validation['loss'], 'o-', linewidth=1, color='red', label='validation')
        axs[1].plot(df_validation['n'], df_validation['acc'], 'o-', linewidth=1, color='red', label='validation')
        axs[0].set_title('final train/val. loss = {:.3f}/{:.3f}'.format(df_train.iloc[-1]['loss'], df_validation.iloc[-1]['loss']))
        axs[1].set_title('final train/val. acc. = {:.3f}/{:.3f}'.format(df_train.iloc[-1]['acc'], df_validation.iloc[-1]['acc']))

    axs[0].set_xlabel('# total samples')
    axs[0].set_ylabel('loss')
    axs[0].legend(loc='best', fontsize=9).get_frame().set_alpha(0.5)
    axs[1].set_xlabel('# total samples')
    axs[1].set_ylabel('accuracy')
    axs[1].legend(loc='best', fontsize=9).get_frame().set_alpha(0.5)
    vmin, vmax = axs[1].get_ylim()
    axs[1].set_ylim(vmin, max(1, vmax))

    fig.subplots_adjust(hspace=0.5)
    return fig, axs

def category_encode(ys):
    assert len(ys.shape) == 1 or len(ys.shape) == 2 and ys.shape[1] == 1
    ys_encoded = np.zeros((ys.shape[0], 1 + np.max(ys)), np.float32)
    for i in range(len(ys)):
        ys_encoded[i, int(ys[i])] = 1.0
    return ys_encoded

def demo():
    parser = argparse.ArgumentParser()
    parser.add_argument('-e', '--epoch', type=int, default=10)
    parser.add_argument('-b', '--batchsize', type=int, default=128)
    parser.add_argument('-d', '--dataset', default='MNIST')
    parser.add_argument('-c', '--classes', type=int, default=10)
    parser.add_argument('-t', '--test_size', type=float, default=0.2)
    parser.add_argument('-l', '--learning_rate', type=float, default=0.001)
    parser.add_argument('-g', '--gradient_noise', type=float, default=0.0)
    parser.add_argument('-w', '--weight_decay', type=float, default=0.0)
    parser.add_argument('-D', '--demo_type', default='single')
    parser.add_argument('-L', '--learning', default='BP')
    parser.add_argument('-T', '--print_test', action='store_true')
    parser.add_argument('--no_plot', action='store_true')
    args = parser.parse_args()

    np.random.seed(1)

    if args.dataset == 'MNIST':
        dataset = sklearn.datasets.fetch_mldata('MNIST original')
        print 'problem: MNIST. lr=0.001, batchsize=50, epoch=20, [(80, relu), (80, relu)] will work (97% test acc)'
    elif args.dataset == 'digits':
        dataset = sklearn.datasets.load_digits()
        print 'problem: digits. lr=0.001, batchsize=50, epoch=400, [(80, relu), (80, relu)] will work (99% test acc)'
    xs = dataset.data.astype(np.float32)
    ys = dataset.target.astype(np.int32)

    if True:
        xs = (xs - xs.min()) / xs.ptp() - 0.5
    xs = xs[ys < args.classes]
    ys = ys[ys < args.classes]
    print 'dataset %d samples %d features. min=%f, max=%f' % (
            xs.shape[0], xs.shape[1], xs.min(), xs.max())


    n_classes = np.max(ys) + 1
    ys = category_encode(ys)
    N = len(ys)
    idx_train, idx_test = sklearn.cross_validation.train_test_split(
            range(N), test_size=args.test_size)
    xs_train, xs_test = xs[idx_train], xs[idx_test]
    ys_train, ys_test = ys[idx_train], ys[idx_test]

    hidden_layers = [
            (80, 'relu', 1),
            (80, 'relu', 1),
            ]
    #hidden_layers = [
    #        (50, 'tanh', 1),
    #        (50, 'tanh', 1),
    #        (50, 'tanh', 1),
    #        (50, 'tanh', 1),
    #        (50, 'tanh', 1),
    #        ]

    if args.demo_type == 'single':
        clf = MLP(xs.shape[1], hidden_layers + [
            (n_classes, 'identity', 1),
            ], 'softmax_cross_entropy',
            learning=args.learning)

        clf.fit(xs_train, ys_train, xs_test, ys_test,
                batchsize=args.batchsize,
                n_epoch=args.epoch,
                learning_rate=args.learning_rate,
                gradient_noise=args.gradient_noise,
                weight_decay=args.weight_decay)

        if args.print_test:
            for p, t in zip(clf.predict(xs_test).argmax(axis=1), ys_test.argmax(axis=1)):
                print p, t, 'o' if p == t else 'x'

        fig, axs = plot_fit_log(clf.get_fit_log())
        fig.suptitle('{} classification with {} learning.'.format(
            args.dataset, args.learning))
        fig.savefig('result_{}_{}.png'.format(args.dataset, args.learning))


    if args.demo_type == 'compare':
        learning_methods = ['BP', 'PI', 'FA', 'FA-PI-W', 'FA-PI-B']
        n_iter = 2
        logs = []
        for learning in learning_methods:
            for iter in range(n_iter):
                clf = MLP(xs.shape[1], hidden_layers + [
                    (n_classes, 'identity', 1),
                    ], 'softmax_cross_entropy',
                    learning=learning)

                clf.fit(xs_train, ys_train, xs_test, ys_test,
                        batchsize=args.batchsize,
                        n_epoch=args.epoch,
                        learning_rate=args.learning_rate,
                        gradient_noise=args.gradient_noise,
                        weight_decay=args.weight_decay)

                df = clf.get_fit_log()
                df.iloc[:]['learning'] = learning
                df.iloc[:]['iter'] = iter
                logs.append(df)
        logs = pd.concat(logs)


        fig, axs = plt.subplots(2, 1)
        for learning in learning_methods:
            # grp contains multiple trials.
            grp = logs[(logs['learning'] == learning) & (logs['type'] == 'validation')].groupby('n')
            ns = grp['n'].first()
            loss = grp['loss'].mean()
            acc = grp['acc'].mean()

            lines = axs[0].plot(ns, loss, '.-', linewidth=1, label=learning)
            axs[1].plot(ns, acc, '.-', linewidth=1, color=lines[0].get_color(), label=learning)

        axs[0].set_xlabel('# total samples')
        axs[0].set_ylabel('loss')
        axs[0].legend(loc='best', fontsize=9).get_frame().set_alpha(0.5)
        axs[1].set_xlabel('# total samples')
        axs[1].set_ylabel('accuracy')
        axs[1].legend(loc='best', fontsize=9).get_frame().set_alpha(0.5)
        vmin, vmax = axs[1].get_ylim()
        axs[1].set_ylim(vmin, max(1, vmax))
        fig.suptitle('{}: mean validation score of {} runs'.format(args.dataset, n_iter))
        fig.subplots_adjust(hspace=0.5)

        fig.savefig('compare_{}.png'.format(args.dataset))

    if not args.no_plot:
        plt.show()

if __name__=='__main__':
    demo()
