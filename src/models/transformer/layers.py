import tensorflow as tf
import tensorflow.keras as tfk
from tensorflow.keras import layers as tfkl
import numpy as np

class PositionalEncoding(tfkl.Layer):
    def __init__(self, position, d_model):
        super(PositionalEncoding, self).__init__()

        a = self.get_angles(np.arange(position)[:, np.newaxis],
                            np.arange(d_model)[np.newaxis, :],
                            d_model)

        a[:, 0::2] = np.sin(a[:, 0::2])
        a[:, 1::2] = np.cos(a[:, 1::2])

        self.pos_enc = a[np.newaxis, ...]
        self.pos_enc = tf.cast(self.pos_enc, dtype=tf.float32)

    def call(self, x):
        seq_len = tf.shape(x)[1]
        return x + self.pos_enc[:, :seq_len, :]

    def get_angles(self, pos, i, d_model):
        w = 1.0 / np.power(10000, (2*(i//2)) / np.float32(d_model))
        return pos * w

class ScaledAttention(tfkl.Layer):
    def __init__(self):
        super(ScaledAttention, self).__init__()

    def call(self, q, k, v, mask):
        qk = tf.matmul(q, k, transpose_b=True)

        dk = tf.cast(tf.shape(k)[-1], tf.float32)
        attention_logits = qk / tf.math.sqrt(dk)

        if mask is not None:
            attention_logits += (mask * -1e9)

        weights = tf.nn.softmax(attention_logits, axis=-1)

        outputs = tf.matmul(weights, v)

        return outputs, weights

class RelativeAttention(tfkl.Layer):
    def __init__(self, max_seq, depth):
        super(RelativeAttention, self).__init__()
        self.max_seq = max_seq
        self.depth = depth
        self.e = None

    def build(self, input_shape):
        self.e = self.add_weight('embedding', shape=[self.max_seq, self.depth])

    def call(self, q, k, v, mask):
        k_len = k.shape[2]
        q_len = q.shape[2]

        e = self.left_embedding(q_len, k_len)
        qe = tf.einsum('bhld,md->bhlm', q, e)
        qe = self.qe_mask(qe)
        kt = tf.transpose(k, [0, 1, 3, 2])
        qkt = tf.matmul(q, kt)
        s_rel = self.skew(qe, k_len, q_len)

        dk = tf.cast(tf.shape(k)[-1], tf.float32)

        attention_logits = (qkt + s_rel) / tf.math.sqrt(dk)

        if mask is not None:
            attention_logits += (mask * -1e9)

        weights = tf.nn.softmax(attention_logits, axis=-1)

        outputs = tf.matmul(weights, v)

        return outputs, weights

    def skew(self, x, k_len, q_len):
        x = tf.pad(x, [[0, 0], [0, 0], [0, 0], [1, 0]])
        x = tf.reshape(x, [-1, x.shape[1], x.shape[-1], x.shape[-2]])
        s_rel = x[:, :, 1:, :]

        if k_len > q_len:
            s_rel = tf.pad(s_rel, [[0, 0], [0, 0], [0, 0], [0, k_len-q_len]])
        elif k_len < q_len:
            s_rel = s_rel[:, :, :, :k_len]

        return s_rel

    def qe_mask(self, qe):
        mask = tf.sequence_mask(tf.range(qe.shape[-1] -1, qe.shape[-1] - qe.shape[-2] -1, -1), qe.shape[-1])

        mask = tf.logical_not(mask)
        mask = tf.cast(mask, dtype=tf.float32)

        return qe * mask

    def left_embedding(self, q_len, k_len):
        start = max(0, self.max_seq - q_len)
        return self.e[start:, :]


class MultiHeadAttention(tfkl.Layer):
    def __init__(self, d_model, num_heads):
        super(MultiHeadAttention, self).__init__()
        self.d_model = d_model
        self.num_heads = num_heads

        assert self.d_model % self.num_heads == 0, "d_model is not divisible by num_heads"

        self.depth = self.d_model // self.num_heads

        self.wv = tfkl.Dense(d_model)
        self.wk = tfkl.Dense(d_model)
        self.wq = tfkl.Dense(d_model)

        self.scaled_attention = ScaledAttention()

        self.dense = tfkl.Dense(d_model)

    def split_heads(self, x, batch_size):
        x = tf.reshape(x, [batch_size, -1, self.num_heads, self.depth])
        return tf.transpose(x, perm=[0, 2, 1, 3])

    def call(self, v, k, q, mask):
        batch_size = tf.shape(q)[0]

        v = self.wv(v)
        k = self.wk(k)
        q = self.wq(q)

        v = self.split_heads(v, batch_size)
        k = self.split_heads(k, batch_size)
        q = self.split_heads(q, batch_size)

        attention, attention_weights = self.scaled_attention(q, k, v, mask)

        attention = tf.transpose(attention, perm=[0, 2, 1, 3])
        attention = tf.reshape(attention, [batch_size, -1, self.d_model])
        output = self.dense(attention)

        return output, attention_weights


class RelativeGlobalAttention(tfkl.Layer):
    def __init__(self, d_model, num_heads, max_seq):
        super(RelativeGlobalAttention, self).__init__()
        self.d_model = d_model
        self.num_heads = num_heads

        assert self.d_model % self.num_heads == 0, "d_model is not divisible by num_heads"

        self.depth = self.d_model // self.num_heads

        self.wv = tfkl.Dense(d_model)
        self.wk = tfkl.Dense(d_model)
        self.wq = tfkl.Dense(d_model)

        self.relative_attention = RelativeAttention(max_seq, self.depth)

        self.dense = tfkl.Dense(d_model)

    def split_heads(self, x, batch_size):
        x = tf.reshape(x, [batch_size, -1, self.num_heads, self.depth])
        return tf.transpose(x, perm=[0, 2, 1, 3])

    def call(self, v, k, q, mask):
        batch_size = tf.shape(q)[0]

        v = self.wv(v)
        k = self.wk(k)
        q = self.wq(q)

        v = self.split_heads(v, batch_size)
        k = self.split_heads(k, batch_size)
        q = self.split_heads(q, batch_size)

        attention, attention_weights = self.relative_attention(q, k, v, mask)

        attention = tf.transpose(attention, perm=[0, 2, 1, 3])
        attention = tf.reshape(attention, [batch_size, -1, self.d_model])
        output = self.dense(attention)

        return output, attention_weights


class PointWiseFF(tfkl.Layer):
    def __init__(self, d_model, dff):
        super(PointWiseFF, self).__init__()
        self.d1 = tfkl.Dense(dff, activation='relu')
        self.d2 = tfkl.Dense(d_model)

    def call(self, x):
        x = self.d1(x)
        x = self.d2(x)
        return x


class EncoderLayer(tfkl.Layer):
    def __init__(self, d_model, num_heads, dff, rate=0.1):
        super(EncoderLayer, self).__init__()

        # self.mha = MultiHeadAttention(d_model, num_heads)
        self.rga = RelativeGlobalAttention(d_model, num_heads, max_seq=2048) # TODO: remove max_seq hardcoding
        self.pwff = PointWiseFF(d_model, dff)

        self.lnorm1 = tfkl.LayerNormalization(epsilon=1e-6)
        self.lnorm2 = tfkl.LayerNormalization(epsilon=1e-6)

        self.dropout1 = tfkl.Dropout(rate)
        self.dropout2 = tfkl.Dropout(rate)

    def call(self, x, training, mask):
        attn_output, _ = self.rga(x, x, x, mask)
        attn_output = self.dropout1(attn_output, training=training)

        out1 = self.lnorm1(x + attn_output)

        ffn_output = self.pwff(out1)
        ffn_output = self.dropout2(ffn_output, training=training)

        out2 = self.lnorm2(out1 + ffn_output)

        return out2


class DecoderLayer(tfkl.Layer):
    def __init__(self, d_model, num_heads, dff, rate=0.1):
        super(DecoderLayer, self).__init__()

        # self.mha1 = MultiHeadAttention(d_model, num_heads)
        # self.mha2 = MultiHeadAttention(d_model, num_heads)
        self.rga1 = RelativeGlobalAttention(d_model, num_heads, max_seq=2048) # TODO: remove max_seq hardcoding
        self.rga2 = RelativeGlobalAttention(d_model, num_heads, max_seq=2048) # TODO: remove max_seq hardcoding

        self.pwff = PointWiseFF(d_model, dff)

        self.lnorm1 = tfkl.LayerNormalization(epsilon=1e-6)
        self.lnorm2 = tfkl.LayerNormalization(epsilon=1e-6)
        self.lnorm3 = tfkl.LayerNormalization(epsilon=1e-6)

        self.dropout1 = tfkl.Dropout(rate)
        self.dropout2 = tfkl.Dropout(rate)
        self.dropout3 = tfkl.Dropout(rate)

    def call(self, x, enc_output, training, look_ahead_mask, padding_mask):
        attn1, attn_weights_block1 = self.rga1(x, x, x, look_ahead_mask)
        attn1 = self.dropout1(attn1, training=training)
        out1 = self.lnorm1(attn1 + x)

        attn2, attn_weights_block2 = self.rga2(enc_output, enc_output, out1, padding_mask)
        attn2 = self.dropout2(attn2, training=training)
        out2 = self.lnorm2(attn2 + out1)

        ffn_output = self.pwff(out2)
        ffn_output = self.dropout3(ffn_output, training=training)
        out3 = self.lnorm3(ffn_output + out2)

        return out3, attn_weights_block1, attn_weights_block2

class Encoder(tfkl.Layer):
    def __init__(self, num_layers, d_model, num_heads, dff, input_vocab_size, max_pos_enc, rate=0.1):
        super(Encoder, self).__init__()

        self.d_model = d_model
        self.num_layers = num_layers

        self.embedding = tfkl.Embedding(input_vocab_size, d_model)
        self.pos_enc = PositionalEncoding(2048, self.d_model)

        self.layers = [EncoderLayer(d_model, num_heads, dff, rate) for _ in range(num_layers)]

        self.dropout = tfkl.Dropout(rate)

    def call(self, x, training, mask):
        x = self.embedding(x)
        x *= tf.math.sqrt(tf.cast(self.d_model, tf.float32))
        x = self.pos_enc(x)

        x = self.dropout(x, training=training)

        for i in range(self.num_layers):
            x = self.layers[i](x, training, mask)

        return x

class Decoder(tfkl.Layer):
    def __init__(self, num_layers, d_model, num_heads, dff, target_vocab_size, max_pos_enc, rate=0.1):
        super(Decoder, self).__init__()

        self.d_model = d_model
        self.num_layers = num_layers

        self.embedding = tfkl.Embedding(target_vocab_size, d_model)
        self.pos_enc = PositionalEncoding(2048, self.d_model)

        self.layers = [DecoderLayer(d_model, num_heads, dff, rate) for _ in range(num_layers)]

        self.dropout = tfkl.Dropout(rate)

    def call(self, x, enc_output, training, look_ahead_mask, padding_mask):
        attention_weights = {}

        x = self.embedding(x)
        x *= tf.math.sqrt(tf.cast(self.d_model, tf.float32))
        x = self.pos_enc(x)

        x = self.dropout(x, training=training)

        for i in range(self.num_layers):
            x, block1, block2 = self.layers[i](x, enc_output, training, look_ahead_mask, padding_mask)
            attention_weights['dec_l{}_b1'.format(i+1)] = block1
            attention_weights['dec_l{}_b2'.format(i+1)] = block2

        return x, attention_weights
