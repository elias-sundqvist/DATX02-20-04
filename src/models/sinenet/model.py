import tensorflow as tf
import numpy as np
import data.process as pro
import tensorflow.keras as tfk
import tensorflow.keras.layers as tfkl

class SineNet():
    def __init__(self, hparams, ft_shape):
        self.hparams = hparams
        self.ft_shape = ft_shape

        self.param_net = self.create_param_net()
        self.optimizer = tfk.optimizers.Adam(hparams['lr'])

    @tf.function
    def get_loss(self, y_target, params):
        wave = self.get_wave(params)
        #loss = tfk.losses.mean_squared_error(y_target, wave)

        wave = tf.signal.stft(wave, 512, 256, 512)
        wave = tf.math.abs(wave)+0.0000001
        wave = tf.math.log(wave)
        #wave = tf.math.reduce_mean(wave, axis=1)
        y_target = tf.signal.stft(y_target, 512, 256, 512)
        y_target = tf.math.abs(y_target)+0.0000001
        y_target = tf.math.log(y_target)
        #y_target = tf.math.reduce_mean(y_target, axis=1)

        specloss = tfk.losses.mean_squared_error(y_target, wave)

        return specloss

    @tf.function
    def train_step(self, x):
        x, y_target = x

        with tf.GradientTape() as tape:
            params = self.param_net(x, training=True)
            
            loss = self.get_loss(y_target, params)


        gradients = tape.gradient(loss, self.param_net.trainable_variables)

        self.optimizer.apply_gradients(zip(gradients, self.param_net.trainable_variables))

        return loss

    def create_param_net(self):
        i = tfkl.Input(shape=self.ft_shape)

        #o = tfkl.Reshape([*self.ft_shape, 1])(i)
        #o = tfkl.Conv2D(8, 3, activation='relu')(o)
        #o = tfkl.Conv2D(8, 3, strides=2, activation='relu')(o)
        #o = tfkl.Conv2D(8, 3, strides=2, activation='relu')(o)
        #o = tfkl.Flatten()(o)
        o = tfkl.Dense(512, activation='relu')(i)
        o = tfkl.Dense(512, activation='relu')(o)
        o = tfkl.Dense(self.hparams['channels']*self.hparams['params'], activation='sigmoid')(o)

        return tfk.Model(inputs=i, outputs=o)


    @tf.function
    def get_wave(self, params):
        batch_size = tf.shape(params)[0]
        params = tf.split(params, num_or_size_splits=self.hparams['params'], axis=1)
        As, Bs, Cs = [tf.reshape(p, [-1, 1, self.hparams['channels']]) for p in params]

        t = tf.reshape(
            tf.tile(
                tf.reshape(
                    tf.linspace(0.0, 1.0, self.hparams['samples']),
                    [1, self.hparams['samples'], 1]),
                [batch_size, 1, self.hparams['channels']]),
            [-1, self.hparams['samples'], self.hparams['channels']])

        i = tf.reshape(tf.range(-45, -45 + self.hparams['channels']), [1, 1, self.hparams['channels']])
        i = tf.cast(i, dtype=tf.float32)
        cos = As*tf.math.cos(t*2*np.pi*440*2**(i/12) - Bs*np.pi*2)
        exp = tf.math.exp(-t*Cs*20)

        wave = tf.math.reduce_sum(cos*exp, axis=2)
        wave = tf.math.tanh(wave)

        return wave
