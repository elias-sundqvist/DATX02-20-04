import tensorflow as tf
import librosa
import data.process as pro
import matplotlib.pyplot as plt
from models.new_gan.process import load, invert
from models.new_gan.model import GAN


def start(hparams):
    dataset, stats = load(hparams)

    def resize(image, down_scale):
        return tf.squeeze(tf.image.resize(tf.reshape(image, [1, 128, 1024, 2]), [128//down_scale, 1024//down_scale]))

    # Stack mag and phase into one tensor
    dataset = dataset.map(lambda mag, phase, pitch: (tf.stack([mag, phase], axis=-1), pitch))

    gan = GAN(hparams, stats)

    # Get the first models to train
    g_init, d_init, gan_init = gan.get_initial_models()

    # Create the smallest scaled dataset to train the first
    scaled_dataset = pro.pipeline([
        pro.map_transform(lambda magphase, pitch: (resize(magphase, 2**(hparams['n_blocks']-1)), pitch)),
        pro.cache(),
    ])(dataset)

    gan.train_epochs(g_init, d_init, gan_init, scaled_dataset, hparams['epochs'][0], hparams['batch_sizes'][0])
    gen = g_init(tf.random.normal([5, hparams['latent_dim']]), training=False)
    plot_magphase(hparams, gen, f'generated_magphase_block00')

    for i in range(1, hparams['n_blocks']):
        down_scale = 2**(hparams['n_blocks']-i-1)
        batch_size = hparams['batch_sizes'][i]
        epochs = hparams['epochs'][i]

        scaled_dataset = pro.pipeline([
            pro.map_transform(lambda magphase, pitch: (resize(magphase, down_scale), pitch)),
            pro.cache(),
        ])(dataset)

        [g_normal, g_fadein] = gan.generators[i]
        [d_normal, d_fadein] = gan.discriminators[i]
        [gan_normal, gan_fadein] = gan.models[i]

        print("\nFading in next...")
        gan.train_epochs(g_fadein, d_fadein, gan_fadein, scaled_dataset, epochs, batch_size, True)

        print("\nNormal training...")
        gan.train_epochs(g_normal, d_normal, gan_normal, scaled_dataset, epochs, batch_size)

        gen = g_normal(tf.random.normal([5, hparams['latent_dim']]), training=False)
        plot_magphase(hparams, gen, f'generated_magphase_block{i:02d}')
       

def plot_magphase(hparams, magphase, name, pitch=None):
    count = magphase.shape[0] if len(magphase.shape) == 4 else 1
    fig, axs = plt.subplots(1, 2*count)
    for i in range(count):
        mag, phase = tf.unstack(magphase[i], axis=-1)
        if pitch is not None:
            plt.suptitle(f"Pitch: {tf.argmax(pitch)}")
        axs[0+i*2].set_title("Mag")
        axs[0+i*2].axes.get_xaxis().set_visible(False)
        axs[0+i*2].axes.get_yaxis().set_visible(False)
        axs[0+i*2].imshow(tf.transpose(mag, [1, 0]))
        axs[1+i*2].set_title("Pha")
        axs[1+i*2].axes.get_xaxis().set_visible(False)
        axs[1+i*2].axes.get_yaxis().set_visible(False)
        axs[1+i*2].imshow(tf.transpose(phase, [1, 0]))

    plt.tight_layout()
    plt.savefig(f'{name}.png')

def invert_magphase(hparams, stats, magphase, name):
    magphase = tf.squeeze(magphase)
    mag, phase = tf.unstack(magphase, axis=-1)
    audio = invert(hparams, stats)((mag, phase))
    librosa.output.write_wav(f'{name}.wav', audio.numpy(), sr=hparams['sample_rate'])
