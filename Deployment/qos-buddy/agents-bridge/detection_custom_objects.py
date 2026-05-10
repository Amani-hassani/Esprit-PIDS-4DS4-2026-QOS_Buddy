"""
Reconstructs the `OptimizedAnomalyDetector` Keras subclass that was used
to train the operator's autoencoder.

The trained `.keras` artefact references this class by registered name
(`Custom>OptimizedAnomalyDetector`). The class definition was never
checked into the runtime backend, so reloading the model failed with
`Could not locate class 'OptimizedAnomalyDetector'`. This module rebuilds
the architecture exactly as inspected from the weight file:

  Encoder: Dense(30→128) BN LeakyReLU Dropout
           Dense(128→64) BN LeakyReLU Dropout
           Dense(64→32)  BN LeakyReLU
           Dense(32→16)                       ← bottleneck
  Decoder: Dense(16→32)  BN LeakyReLU Dropout
           Dense(32→64)  BN LeakyReLU Dropout
           Dense(64→128) BN LeakyReLU
           Dense(128→30)                       ← reconstruction

Importing this module triggers `@keras.saving.register_keras_serializable`,
which makes Keras's loader find the class. The runtime imports the module
once at startup; nothing else changes.
"""

from __future__ import annotations

import keras
from keras import layers


@keras.saving.register_keras_serializable(package="Custom", name="OptimizedAnomalyDetector")
class OptimizedAnomalyDetector(keras.Model):
    def __init__(self, input_dim: int = 30, **kwargs):
        super().__init__(**kwargs)
        self.input_dim = input_dim

        self.encoder = keras.Sequential(
            [
                layers.Dense(128),
                layers.BatchNormalization(),
                layers.LeakyReLU(),
                layers.Dropout(0.2),
                layers.Dense(64),
                layers.BatchNormalization(),
                layers.LeakyReLU(),
                layers.Dropout(0.2),
                layers.Dense(32),
                layers.BatchNormalization(),
                layers.LeakyReLU(),
                layers.Dense(16),
            ],
            name="encoder",
        )
        self.decoder = keras.Sequential(
            [
                layers.Dense(32),
                layers.BatchNormalization(),
                layers.LeakyReLU(),
                layers.Dropout(0.2),
                layers.Dense(64),
                layers.BatchNormalization(),
                layers.LeakyReLU(),
                layers.Dropout(0.2),
                layers.Dense(128),
                layers.BatchNormalization(),
                layers.LeakyReLU(),
                layers.Dense(input_dim),
            ],
            name="decoder",
        )

    def call(self, x, training=False):
        z = self.encoder(x, training=training)
        return self.decoder(z, training=training)

    def get_config(self):
        config = super().get_config()
        config.update({"input_dim": self.input_dim})
        return config
