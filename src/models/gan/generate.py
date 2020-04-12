import tensorflow as tf
from models.common.training import Trainer
from models.gan.model import GAN
import librosa
import matplotlib.pyplot as plt
import data.process as pro
import numpy as np


def start(hparams):
    gan_stats = np.load('gan_stats.npz')

    gan = GAN((128, 128), hparams)

    trainer = Trainer(None, hparams)

    ckpt = tf.train.Checkpoint(
        step=trainer.step,
        generator=gan.generator,
        discriminator=gan.discriminator,
        gen_optimizer=gan.generator_optimizer,
        disc_optimizer=gan.discriminator_optimizer,
    )

    trainer.init_checkpoint(ckpt)

    count = 16

    seed = tf.random.normal((count, hparams['latent_size']))
    #seed = tf.repeat(seed, count, axis=0)
    mid = hparams['cond_vector_size']//2
    pitches = tf.one_hot(range(mid-count//2, mid+count//2), hparams['cond_vector_size'], axis=1)

    samples = tf.reshape(gan.generator([seed, pitches], training=False), [-1, 128, 128])
    x = tf.unstack(samples)

    width = 4
    height = 4
    plt.figure(figsize=(width*2, height*2))

    for i, img in enumerate(x):
        plt.subplot(width, height, i+1)
        plt.title(i)
        plt.imshow(tf.reverse(x[i], axis=[0]))
        plt.axis('off')

    plt.savefig('output.png')
    audio = pro.pipeline([
        pro.denormalize(normalization='specgan', stats=gan_stats),
        pro.invert_log_melspec(hparams['sample_rate'])
    ])(x)

    output = np.concatenate(list(audio))

    librosa.output.write_wav('gan_sample.wav', output, hparams['sample_rate'])
