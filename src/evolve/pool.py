import random
from evolve.hparams import HParams

class Pool():
    def __init__(self, create_model, hparams_template):
        self.pool = []
        self.create_model = create_model
        self.hparams = HParams(hparams_template)

    def generate(self, mutation_rate, old):
        hp = self.hparams.generate(mutation_rate, old)
        return (hp, self.create_model(hp))

    def populate(self, size, mutation_rate=0.1):
        self.pool = [self.generate(mutation_rate,
                                   self.pool[i][0] if 0 <= i < len(self.pool) else None)
                     for i in range(size)]
        return self

    def evaluate(self, fitness_fn):
        self.fitness = [(fitness_fn(model[1]), i)
                        for i, model in enumerate(self.pool)]
        self.fitness.sort(reverse=True)
        return self

    def select(self, count):
        selected = []

        # Tournament selection
        for _ in range(count):
            f1, i1 = self.fitness[random.randrange(len(self.fitness))]
            f2, i2 = self.fitness[random.randrange(len(self.fitness))]
            if f1 > f2:
                selected.append(i1)
            elif f2 > f1:
                selected.append(i2)
            else:
                if random.random() < 0.5:
                    selected.append(i1)
                else:
                    selected.append(i2)

        self.pool = [self.pool[i] for i in selected]

        return self
