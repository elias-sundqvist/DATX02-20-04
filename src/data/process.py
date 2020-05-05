import tensorflow as tf
import librosa
import mido
import math
import numpy as np
import itertools

def index_map(index, f):
    # Carl: I don't think this parallelizes very well, but I'm not sure
    def imap(x):
        x[index] = f(x[index])
        return x
    return map_transform(imap)

def pipeline(transforms):
    def transform(dataset):
        for trns in transforms:
            dataset = trns(dataset)
        return dataset
    return transform

def map_transform(fn):
    def transform(dataset):
        if isinstance(dataset, tf.data.Dataset):
            return dataset.map(fn, num_parallel_calls=tf.data.experimental.AUTOTUNE)
        elif not isinstance(dataset, tf.Tensor):
            return map(fn, dataset)
        else:
            return fn(dataset)
    return transform

def numpy():
    def transform(dataset):
        if isinstance(dataset, tf.data.Dataset):
            return dataset.as_numpy_iterator()
        else:
            return dataset
    return transform

def tensor(output_types):
    def transform(dataset):
        if isinstance(dataset, tf.data.Dataset):
            return dataset
        else:
            def _generator():
                for x in dataset:
                    yield x
            return tf.data.Dataset.from_generator(_generator, output_types)
    return transform

def filter_transform(fn):
    def transform(dataset):
        if isinstance(dataset, tf.data.Dataset):
            return dataset.filter(fn)
        else:
            return filter(fn, dataset)
    return transform


#
# TRANSFORMS
#
def parse_tfrecord(features):
    return map_transform(lambda x: tf.io.parse_single_example(x, features))

def resample(orig_sr, target_sr, dtype=None):
    return map_transform(lambda x: tf.reshape(tf.py_function(lambda x: librosa.core.resample(x.numpy(), orig_sr=orig_sr, target_sr=target_sr), [tf.reshape(x, [-1])], x.dtype if dtype is None else dtype), [-1]))

def read_file():
    return map_transform(lambda x: tf.io.read_file(x))

def decode_wav(desired_channels=-1, desired_samples=-1):
    return map_transform(lambda x: tf.audio.decode_wav(x, desired_channels, desired_samples))

def wav(desired_channels=-1, desired_samples=-1):
    return pipeline([
        read_file(),
        decode_wav(desired_channels, desired_samples),
        map_transform(lambda x: x[0]),
        reshape([-1]),
    ])

def one_hot(depth):
    return map_transform(lambda x: tf.one_hot(x, depth))

def filter(predicate):
    return filter_transform(predicate)

def extract(key):
    return map_transform(lambda x: x[key])

def reshape(shape):
    return map_transform(lambda x: tf.reshape(x, shape))

# def set_channels(channels):
#     return map_transform(lambda x: tf.reshape(x, [-1, channels]))

def cache(filename=''):
    return lambda dataset: dataset.cache(filename)

def batch(batch_size, drop_remainder=False):
    return lambda dataset: dataset.batch(batch_size, drop_remainder)

def unbatch():
    return lambda dataset: dataset.unbatch()

def shuffle(buffer_size):
    return lambda dataset: dataset.shuffle(buffer_size)

def prefetch():
    return lambda dataset: dataset.prefetch(tf.data.experimental.AUTOTUNE)

def pad(paddings, mode, constant_values=0, name=None):
    return map_transform(_pad(paddings, mode, constant_values, name))

def _pad(paddings, mode, constant_values=0, name=None):
    def _p(x):
        if type(constant_values) == str:
            if constant_values == 'min':
                values = tf.reduce_min(x)
            elif constant_values == 'max':
                values = tf.reduce_max(x)
        else:
            values = constant_values
        return tf.pad(x, paddings, mode, values, name)
    return _p


def frame(frame_length, frame_step, pad_end=False, pad_value=0, axis=-1, name=None):
    return map_transform(lambda x: tf.signal.frame(x, frame_length,
                                                          frame_step, pad_end,
                                                          pad_value, axis, name))

def split(num_or_size_splits, axis=0, num=None, name='split'):
    return map_transform(lambda x: tf.split(x, num_or_size_splits,
                                                   axis, num, name))

def debug():
    return map_transform(lambda x: tf.py_function(_debug, [x], x.dtype))

def _debug(x):
    print(x)
    return x

def stft(n_fft, hop_length, win_length):
    print(f'stft: {n_fft} {hop_length} {win_length}')
    temp = lambda x: librosa.stft(
        x.numpy(),
        n_fft=n_fft,
        hop_length=hop_length,
        win_length=win_length,
    )
    
    return map_transform(lambda x: tf.py_function(temp, [x], tf.complex64))

def istft(win_length, hop_length):
    print(f'istft: {hop_length} {win_length}')
    temp = lambda x: librosa.istft(
            x.numpy(),
            hop_length=hop_length,
            win_length=win_length,
            )

    return map_transform(lambda x: tf.py_function(temp, [x], tf.float32))

def stft_spec(n_fft, hop_length, win_length):
    print(f'stft_spec: {n_fft} {hop_length} {win_length}')
    def temp(x):
        mag = librosa.amplitude_to_db(np.abs(x), ref=1.0)
        phase = phase_to_inst_freq(np.angle(x))
        magphase = np.transpose([mag, phase], [1,2,0])
        magphase = magphase[:-3,:,:]
        return magphase

    return pipeline([
        stft(
            n_fft=n_fft,
            hop_length=hop_length,
            win_length=win_length
            ),
        lambda x: tf.py_function(temp, [x], tf.float32),
    ])

def istft_spec(hop_length, win_length):
    print(f'istft_spec: {hop_length} {win_length}')
    def temp(magphase):
        magphase = tf.unstack(magphase, axis=-1)
        mag = magphase[0]
        phase = magphase[1]

        mag = tf.cast(librosa.db_to_amplitude(mag.numpy(), ref=1.0), tf.complex64)
        phase = tf.cast(inst_freq_to_phase(phase.numpy()), tf.complex64)

        out = mag * tf.math.exp(1.0j * phase)
        return out

    return pipeline([
        lambda x: tf.py_function(temp, [x], tf.complex64),
        istft(
            hop_length=hop_length,
            win_length=win_length
            ),
    ])


def abs():
    return map_transform(lambda x: tf.abs(x))

def dupe():
    return map_transform(lambda x: (x, x))

def _normalize(normalization='neg_one_to_one', **kwargs):
    def _n(x):
        _max = tf.math.reduce_max(x)
        _min = tf.math.reduce_min(x)
        if normalization == 'neg_one_to_one':
            return ((x - _min) / (_max - _min)) * 2 - 1
        elif normalization == 'zero_to_one':
            return ((x - _min) / (_max - _min))
        elif normalization == 'specgan':
            stats = kwargs['stats']
            std = tf.math.sqrt(stats['variance'])
            norm = (x - stats['mean']) / (3*std)
            clipped = tf.math.minimum(tf.math.maximum(norm, -1), 1)
            return clipped
        elif normalization == 'specgan_two_channel':
            unstacked = tf.unstack(x, 2, axis=-1)
            spec = unstacked[0]
            phase = unstacked[1]


            stats = kwargs['stats']

            s_std = tf.math.sqrt(stats['s_variance'])
            s_norm = (spec - stats['s_mean']) / (3*s_std)
            s_clipped = tf.math.minimum(tf.math.maximum(s_norm, -1), 1)

            # p_std = tf.math.sqrt(stats['p_variance']) + 0.000000001
            # p_norm = (phase - stats['p_mean']) / (3*p_std)
            p_clipped = phase#tf.math.minimum(tf.math.maximum(p_norm, -1), 1)

            tf.debugging.check_numerics(stats['p_mean'], 'p_stats mean')
            tf.debugging.check_numerics(phase, 'phase')
            # tf.debugging.check_numerics(p_std, 'p_std')
            # tf.debugging.check_numerics(p_norm, f'p_norm')
            # tf.debugging.check_numerics(p_clipped, 'p_clipped')

            stacked = tf.stack([s_clipped, p_clipped], axis=-1)
            return stacked
    return _n

def normalize(normalization='neg_one_to_one', **kwargs):
    return map_transform(_normalize(normalization, **kwargs))

def amp_to_log(amin=1e-5):
    return map_transform(lambda x: tf.math.log(x + amin))

def log_to_amp(amin=1e-5):
    return map_transform(lambda x: tf.math.exp(x) - amin)

def mels(sr, n_fft, n_mels=128, fmin=0.0, fmax=None):
    if fmax is None:
        fmax = sr / 2.0
    def mel(x):
        #fft_length = x.shape[-1]
        linear_to_mel_weight_matrix = tf.signal.linear_to_mel_weight_matrix(
            n_mels, n_fft, sr, fmin, fmax)

        return tf.tensordot(x, linear_to_mel_weight_matrix, 1)
    return map_transform(mel)

def transpose2d():
    return map_transform(lambda x: tf.transpose(x, [1, 0]))

def spec(fft_length=1024, frame_step=512, frame_length=None, **kwargs):
    if frame_length is None:
        frame_length = fft_length
    return pipeline([
        stft(frame_length, frame_step, fft_length),
        abs(),
        transpose2d()
    ])

def melspec(sr, n_mels=256, n_fft=1024, hop_length=512, win_length=None, **kwargs):
    return pipeline([
        map_transform(lambda x: tf.py_function(lambda x: librosa.feature.melspectrogram(x.numpy(), sr=sr, n_fft=n_fft, n_mels=n_mels, hop_length=hop_length, win_length=win_length), [x], x.dtype)),
        map_transform(lambda x: tf.py_function(lambda x: librosa.core.power_to_db(x.numpy(), ref=1.0), [x], x.dtype)),
        # stft(frame_length, frame_step, fft_length),
        # abs(),
        # mels(sr, fft_length//2+1, **kwargs),
        # transpose2d()
    ])

def cqt(sr=16000, hop_length=512, n_bins=256, bins_per_octave=80, filter_scale=0.8, fmin=librosa.note_to_hz("C2")):
        return map_transform(lambda x: tf.py_function(lambda x: librosa.cqt(
            x.numpy(),
            sr=sr,
            hop_length=hop_length,
            bins_per_octave=bins_per_octave,
            n_bins=n_bins,
            filter_scale=filter_scale,
            fmin=fmin,
        ), [x], x.dtype))


def icqt(sr=16000, hop_length=512, n_bins=256, bins_per_octave=80, filter_scale=0.8, fmin=librosa.note_to_hz("C2")):
    return map_transform(lambda x: tf.py_function(lambda x: librosa.core.icqt(
        x.numpy(),
        sr=sr,
        hop_length=hop_length,
        bins_per_octave=bins_per_octave,
        filter_scale=filter_scale,
        fmin=fmin,
    ), [x], x.dtype))

def phase_to_inst_freq(phase):
    return pipeline([
        np.unwrap,
        lambda x: x[:, 1:] - x[:, :-1],
        lambda x: np.concatenate([x[:, 0:1], x], axis=1),
        lambda x: x / np.pi,
    ])(phase)

def inst_freq_to_phase(freq):
    return pipeline([
        lambda x: x * np.pi,
        lambda x: tf.math.cumsum(x, axis=1),
        lambda x: (x + np.pi) % (2 * np.pi) - np.pi,
    ])(freq)


def cqt_spec(sr=16000, hop_length=512, n_bins=256, bins_per_octave=80, filter_scale=0.8, fmin=librosa.note_to_hz("C2")):
    def temp(x):
        mag = librosa.amplitude_to_db(np.abs(x), ref=1.0)
        phase = phase_to_inst_freq(np.angle(x))
        magphase = np.transpose([mag, phase], [1,2,0])
        return magphase

    return pipeline([
        cqt(sr=sr, hop_length=hop_length, n_bins=n_bins, bins_per_octave=bins_per_octave, filter_scale=filter_scale, fmin=fmin),

        lambda x: tf.py_function(temp, [x], x.dtype)

        #map_transform(lambda mag, phase: [mag, phase])
    ])

def inverse_cqt_spec(sr=16000, hop_length=512, n_bins=256, bins_per_octave=80, filter_scale=0.8, fmin=librosa.note_to_hz("C2")):
    def temp(magphase):
        mag = magphase[:,:,0]
        phase = magphase[:,:,1]

        mag = tf.cast(tf.py_function(lambda x: librosa.db_to_amplitude(x.numpy(), ref=1.0), [mag], mag.dtype), tf.complex64)
        phase = tf.cast(tf.py_function(inst_freq_to_phase, [phase], phase.dtype), tf.complex64)
        out = mag * tf.math.exp(1.0j * phase)
        return out

    return pipeline([
        map_transform(temp),
        icqt(),
        lambda x: tf.cast(x, tf.float32)
    ])


def denormalize(normalization='neg_one_to_one', **kwargs):
    def two_channel_denorm(x, stats):
        print("X SHAPE", x.shape)
        magphase = tf.unstack(x, axis=-1)
        mag = magphase[0]
        phase = magphase[1]

        s_std = tf.math.sqrt(stats['s_variance'])
        # p_std = tf.math.sqrt(stats['p_variance'])
        mag = mag * (3.0 * s_std) + stats['s_mean']
        # phase = mag * (3.0 * p_std) + stats['p_mean']

        stacked = tf.stack([mag, phase], axis=-1)
        return stacked

    if normalization == 'neg_one_to_one':
        return map_transform(lambda x: (((x+1)*0.5)*(kwargs['denorm_amax']-kwargs['denorm_amin'])+kwargs['denorm_amin']))
    elif normalization == 'zero_to_one':
        return map_transform(lambda x: (x*(kwargs['denorm_amax']-kwargs['denorm_amin'])+kwargs['denorm_amin']))
    elif normalization == 'specgan':
        stats = kwargs['stats']
        std = tf.math.sqrt(stats['variance'])
        return map_transform(lambda x: (x * (3.0 * std)) + stats['mean'])
    elif normalization == 'specgan_two_channel':
        stats = kwargs['stats']
        return map_transform(lambda x: two_channel_denorm(x, stats))
    else:
        raise Exception(f"No normalization type named '{normalization}'.")

def invert_log_melspec(sr, n_mels=256, n_fft=1024, hop_length=512, win_length=None, amin=1e-5, denorm_amin=-38, denorm_amax=0):
    return pipeline([
        # denormalize(denorm_amin, denorm_amax),
        # log_to_amp(amin),
        map_transform(lambda x: librosa.core.db_to_power(x, ref=1.0)),
        map_transform(lambda x: librosa.feature.inverse.mel_to_audio(x, sr=sr, n_fft=n_fft, hop_length=hop_length, win_length=win_length))
    ])

def load_midi():
    return map_transform(lambda x: mido.MidiFile(x))


def encode_midi(note_count=128, time_shift_count=100, time_shift_ms=10, velocity_count=100):
    _event_start = {
        'note_on': 0,
        'note_off': note_count,
        'time_shift': note_count * 2,
        'velocity': note_count * 2 + time_shift_count,
    }

    def _midi(x):
        midi = []
        prev_note = 0
        for msg in x:
            if not msg.is_meta:
                time_shift = min(int(msg.time*1000) // time_shift_ms, time_shift_count-1)

                if msg.type == 'note_on':
                    midi.append(min(msg.note, note_count-1) + _event_start['note_on'])
                    midi.append(min(msg.velocity, velocity_count-1) + _event_start['velocity'])
                    prev_note = msg.note
                else:# msg.type == 'note_off':
                    midi.append(min(prev_note, note_count-1) + _event_start['note_off'])

                midi.append(time_shift+_event_start['time_shift'])

        return tf.cast(tf.stack(midi), dtype=tf.int64)
    return map_transform(_midi)

def decode_midi(note_count=128, time_shift_count=100, time_shift_ms=10, velocity_count=100):
    note_on_range = range(0, note_count)
    note_off_range = range(note_count, note_count*2)
    time_shift_range = range(note_count*2, note_count*2+time_shift_count)

    def _midi(x):
        mid = mido.MidiFile()
        track = mido.MidiTrack()
        mid.tracks.append(track)

        msgs = []
        prev_msg = None
        for e in x.numpy():
            print(e)
            e = int(e)
            print(e)
            if e in note_on_range:
                msg = {'type': 'note_on', 'note': e}
                msgs.append(msg)
                prev_msg = msg
            elif e in note_off_range:
                msg = {'type': 'note_off'}
                msgs.append(msg)
                prev_msg = msg
            elif e in time_shift_range and prev_msg is not None:
                prev_msg['time_shift'] = e - note_count*2
            elif prev_msg is not None:
                prev_msg['velocity'] = e - note_count*2 - time_shift_count

        print(msgs)
        note_on = False
        for msg in msgs:
            if msg['type'] == 'note_on':
                # if 'velocity' not in msg and 'time_shift' not in msg:
                #     break
                track.append(mido.Message('note_on',
                                          note=msg['note'],
                                          velocity=msg['velocity'] if 'velocity' in msg else 20,
                                          time=msg['time_shift']*time_shift_ms if 'time_shift' in msg else 50))
                note_on = True
            else:
                # if 'time_shift' not in msg:
                #     break
                track.append(mido.Message('note_off',
                                          time=msg['time_shift']*time_shift_ms if 'time_shift' in msg else 50))
                note_on = False
        print(track)

        return mid
    return map_transform(_midi)

def midi(note_count=128, max_time_shift=100, time_shift_m=10):
    return pipeline([
        numpy(),
        load_midi(),
        encode_midi(note_count, max_time_shift, time_shift_m),
        tensor(tf.int64),
    ])
