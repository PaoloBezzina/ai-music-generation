from __future__ import print_function, division

# Recursive GAN (RNN-GAN), Musical notes are transformed into a numerical scale and normalized for inputs into the NN
import matplotlib.pyplot as plt
import numpy as np
import glob
from music21 import converter, instrument, note, chord, stream
from keras.layers import Input, Dense, Reshape, LSTM, Bidirectional
from keras.layers import BatchNormalization
from keras.layers.advanced_activations import LeakyReLU
from keras.models import Sequential, Model
from keras.optimizers import Adam
from keras.utils import np_utils

length = 200
offset_increment = 0.5
alpha = 0.2

# Using music21 to extract relevant information from the MIDI files (note, chord, pitch, structure)
def get_notes():
    """ Get all the notes and chords (groups of notes) from the midi files """
    notes = []

    #for file in glob.glob("Datasets/Pokemon MIDIs/*.mid"):
    for file in glob.glob("Datasets/Beethoven/*.mid"):
    #for file in glob.glob("Datasets/*.mid"):
        midi = converter.parse(file)

        print("Parsing %s" % file)

        notes_to_parse = None

        try:  # file has instrument parts
            s2 = instrument.partitionByInstrument(midi)
            notes_to_parse = s2.parts[0].recurse()
        except:  # file has notes in a flat structure
            notes_to_parse = midi.flat.notes

        for element in notes_to_parse:
            if isinstance(element, note.Note):
                notes.append(str(element.pitch))
            elif isinstance(element, chord.Chord):
                notes.append('.'.join(str(n) for n in element.normalOrder))

    return notes

# Their sequence is maintained and each note is represented as its specific note-type or a corresponding number.
# They are converted to a -1 to 1 scale
def prepare_sequences(notes, n_vocab):
    """ Prepare the sequences used by the Neural Network """
    sequence_length = length

    # Get all pitch names
    pitchnames = sorted(set(item for item in notes))

    # Create a dictionary to map pitches to integers
    note_to_int = dict((note, number) for number, note in enumerate(pitchnames))

    network_input = []
    network_output = []

    # create input sequences and the corresponding outputs
    for i in range(0, len(notes) - sequence_length, 1):
        sequence_in = notes[i:i + sequence_length]
        sequence_out = notes[i + sequence_length]
        network_input.append([note_to_int[char] for char in sequence_in])
        network_output.append(note_to_int[sequence_out])

    n_patterns = len(network_input)

    # Reshape the input into a format compatible with LSTM layers
    network_input = np.reshape(network_input, (n_patterns, sequence_length, 1))

    # Normalize input between -1 and 1
    network_input = (network_input - float(n_vocab) / 2) / (float(n_vocab) / 2)
    network_output = np_utils.to_categorical(network_output)

    return network_input, network_output


def create_midi(prediction_output, filename):
    """ convert the output from the prediction to notes and create a midi file
        from the notes """
    offset = 0
    output_notes = []

    # create note and chord objects based on the values generated by the model
    for item in prediction_output:
        pattern = item[0]
        # pattern is a chord
        if ('.' in pattern) or pattern.isdigit():
            notes_in_chord = pattern.split('.')
            notes = []
            for current_note in notes_in_chord:
                new_note = note.Note(int(current_note))
                new_note.storedInstrument = instrument.Piano()
                notes.append(new_note)
            new_chord = chord.Chord(notes)
            new_chord.offset = offset
            output_notes.append(new_chord)
        # pattern is a note
        else:
            new_note = note.Note(pattern)
            new_note.offset = offset
            new_note.storedInstrument = instrument.Piano()
            output_notes.append(new_note)

        # increase offset each iteration so that notes do not stack
        offset += offset_increment

    midi_stream = stream.Stream(output_notes)
    midi_stream.write('midi', fp='{}.mid'.format(filename))


# Generates music from the Music21 converted inputs. The discriminator and generator model are trained and tested
# simultaneously (pitted against each other) The discriminator is given real data and fake data from random noise.
# With each sample the discriminator must correctly classify data as either fake or real The generator is generating
# fake data from the random noise with the aim of fooling the discriminator with the aim of making it make more
# mistakes (calling a real song "fake" or vice versa). Thus both models compete with the end result being that the
# generator easily fools the discriminator

class GAN():
    def __init__(self, rows):
        self.seq_length = rows
        self.seq_shape = (self.seq_length, 1)
        self.latent_dim = 1000
        self.disc_loss = []
        self.gen_loss = []

        optimizer = Adam(0.0002, 0.5)

        # Build and compile the discriminator
        self.discriminator = self.build_discriminator()
        self.discriminator.compile(loss='binary_crossentropy', optimizer=optimizer, metrics=['accuracy'])

        # Build the generator
        self.generator = self.build_generator()

        # The generator takes noise as input and generates note sequences
        z = Input(shape=(self.latent_dim,))
        generated_seq = self.generator(z)

        # For the combined model we will only train the generator
        self.discriminator.trainable = False

        # The discriminator takes generated images as input and determines validity
        validity = self.discriminator(generated_seq)

        # The combined model  (stacked generator and discriminator)
        # Trains the generator to fool the discriminator
        self.combined = Model(z, validity)
        self.combined.compile(loss='binary_crossentropy', optimizer=optimizer)

    # Here the first two layers are LSTM (Long Short-Term Memory) layers this helps the discriminator to learn from
    # the music inputs as sequential data during training. Without these layers the discriminator is unable to
    # distinguish real music from fake music if the generator figured out the discrete domain of the input data
    # Basically with LSTM the generator has to do more than just figure of the domain of the real data It also needs
    # to figure out that music has to follow certain patterns. Sigmoid activation function is used as our outputs to
    # be a single 0 or 1, representing fake or real data.
    def build_discriminator(self):

        model = Sequential()
        model.add(LSTM(512, input_shape=self.seq_shape, return_sequences=True))
        model.add(Bidirectional(LSTM(512)))
        model.add(Dense(512))
        model.add(LeakyReLU(alpha))
        model.add(Dense(256))
        model.add(LeakyReLU(alpha))
        model.add(Dense(1, activation='sigmoid'))
        model.summary()

        seq = Input(shape=self.seq_shape)
        validity = model(seq)

        return Model(seq, validity)

    # Multi-layered perceptron that receives random inputs equal to the size of the latent dimension 1000 which gives
    # better learning
    def build_generator(self):

        model = Sequential()
        model.add(Dense(256, input_dim=self.latent_dim))
        model.add(LeakyReLU(alpha))
        model.add(BatchNormalization(momentum=0.8))
        model.add(Dense(512))
        model.add(LeakyReLU(alpha))
        model.add(BatchNormalization(momentum=0.8))
        model.add(Dense(1024))
        model.add(LeakyReLU(alpha))
        model.add(BatchNormalization(momentum=0.8))
        model.add(Dense(np.prod(self.seq_shape), activation='tanh'))
        model.add(Reshape(self.seq_shape))
        model.summary()

        noise = Input(shape=(self.latent_dim,))
        seq = model(noise)

        return Model(noise, seq)

    # Firstly the generator is given a batch of random noise from a standard normal distribution and have it process
    # This noise to make a batch of sequences of 100 notes encoded as numbers. This data is then passed to the
    # discriminator as a set of fake data, and the discriminator goes through a training iteration Moreover,
    # the generator makes another set of fake data, And this is passed to the stacked model as fake data to train
    # both the discriminator and the generator
    def train(self, epochs, batch_size=128, sample_interval=50):
        
        # Load and convert the data
        notes = get_notes()
        n_vocab = len(set(notes))
        X_train, y_train = prepare_sequences(notes, n_vocab)

        # Adversarial ground truths
        real = np.ones((batch_size, 1))
        fake = np.zeros((batch_size, 1))

        # Training the model
        for epoch in range(epochs):

            # Training the discriminator
            # Select a random batch of note sequences
            idx = np.random.randint(0, X_train.shape[0], batch_size)
            real_seqs = X_train[idx]

            # noise = np.random.choice(range(484), (batch_size, self.latent_dim))
            # noise = (noise-242)/242
            noise = np.random.normal(0, 1, (batch_size, self.latent_dim))

            # Generate a batch of new note sequences
            gen_seqs = self.generator.predict(noise)

            # Train the discriminator
            d_loss_real = self.discriminator.train_on_batch(real_seqs, real)
            d_loss_fake = self.discriminator.train_on_batch(gen_seqs, fake)
            d_loss = 0.5 * np.add(d_loss_real, d_loss_fake)

            #  Training the Generator
            noise = np.random.normal(0, 1, (batch_size, self.latent_dim))

            # Train the generator (to have the discriminator label samples as real)
            g_loss = self.combined.train_on_batch(noise, real)

            # Print the progress and save into loss lists
            if epoch % sample_interval == 0:
                print("%d [D loss: %f, acc.: %.2f%%] [G loss: %f]" % (epoch, d_loss[0], 100 * d_loss[1], g_loss))
                self.disc_loss.append(d_loss[0])
                self.gen_loss.append(g_loss)

        self.generate(notes)
        self.plot_loss()

    # After training both of the models, we want to generate new MIDI files. For both models, we want to use the
    # model to make a prediciton from an input and create an encoded output that corresponds to a sequence of notes
    # and chords For the GAN network we feed the generator a random sequence of numbers sampled from a standard
    # normal distribution and have it make its predcition. With these predictions, we use Music21 to turn our
    # predicted sequences into brande new midi files
    def generate(self, input_notes):
        # Get pitch names and store in a dictionary
        notes = input_notes
        pitchnames = sorted(set(item for item in notes))
        int_to_note = dict((number, note) for number, note in enumerate(pitchnames))

        # Use random noise to generate sequences
        noise = np.random.normal(0, 1, (1, self.latent_dim))
        predictions = self.generator.predict(noise)

        pred_notes = [x * 242 + 242 for x in predictions[0]]
        pred_notes = [int_to_note[int(x)] for x in pred_notes]

        create_midi(pred_notes, 'static/ganOutputs/ganOutput')

    def plot_loss(self):
        plt.plot(self.disc_loss, c='red')
        plt.plot(self.gen_loss, c='blue')
        plt.title("GAN Loss per Epoch")
        plt.legend(['Discriminator', 'Generator'])
        plt.xlabel('Epoch')
        plt.ylabel('Loss')
        plt.savefig('GAN_Loss_per_Epoch_final.png', transparent=True)
        plt.close()

def runGan(l, off_inc, a):

    global length
    length = l

    global offset_increment
    offset_increment = off_inc

    global alpha
    alpha = a

    print(length, offset_increment,alpha)

    gan = GAN(rows=length)
    gan.train(epochs=5, batch_size=32, sample_interval=1)

if __name__ == '__main__':
    gan = GAN(rows=length)
    gan.train(epochs=200, batch_size=32, sample_interval=1)