import tensorflow as tf
import numpy as np
import tensorflow.keras as tfk
import tensorflow.keras.layers as tfkl

class SineNet():
    def __init__(self, hparams, ft_shape):
        self.hparams = hparams
        self.ft_shape = ft_shape

        self.param_net = self.create_param_net()
        self.optimizer = tfk.optimizers.Adam(hparams['lr'])

    @tf.function
    def train_step(self, x):
        x, y_target = x

        with tf.GradientTape() as tape:
            params = self.param_net(x, training=True)

            wave = self.get_wave(params)

            loss = tfk.losses.mean_squared_error(y_target, wave)

        gradients = tape.gradient(loss, self.param_net.trainable_variables)

        self.optimizer.apply_gradients(zip(gradients, self.param_net.trainable_variables))

        return loss

    def create_param_net(self):
        i = tfkl.Input(shape=self.ft_shape)

        o = tfkl.Dense(128, activation='relu')(i)
        o = tfkl.Dense(128, activation='relu')(o)
        o = tfkl.Dense(32, activation='relu')(o)
        o = tfkl.Dense(self.hparams['channels']*2)(o)
        o = tfkl.Flatten()(o)

        return tfk.Model(inputs=i, outputs=o)


    @tf.function
    def get_wave(self, params):
        As, Bs = tf.split(params, num_or_size_splits=2, axis=1)
        As = tf.reshape(As, [-1, 1, self.hparams['channels']])
        Bs = tf.reshape(Bs, [-1, 1, self.hparams['channels']])

        t = tf.reshape(
            tf.tile(
                tf.reshape(
                    tf.linspace(0.0, 1.0, self.hparams['samples']),
                    [1, self.hparams['samples'], 1]),
                [tf.shape(params)[0], 1, self.hparams['channels']]),
            [-1, self.hparams['samples'], self.hparams['channels']])

        exp = tf.math.exp(-t*As)
        sin = tf.math.sin(t*np.pi*2*440*Bs)

        wave = tf.math.tanh(exp*sin)
        wave = tf.math.reduce_sum(wave, axis=2)

        return wave