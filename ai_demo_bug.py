import random
import statistics
from datetime import datetime

class SimpleAIPredictor:
    def __init__(self, name):
        self.name = name
        self.history = []

    def log(self, message):
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {message}")

    def preprocess(self, data):
        self.log("Preprocessing data...")
        cleaned = [x for x in data if x is not None]
        normalized = [x / max(cleaned) for x in cleaned]  # normalize
        return normalized

    def train(self, data):
        self.log("Training model...")
        self.history.extend(data)

    def predict(self, new_data):
        self.log("Making predictions...")
        if not self.history:
            raise ValueError("Model has not been trained.")

        avg = statistics.mean(self.history)
        predictions = []

        for x in new_data:
            noise = random.uniform(-0.05, 0.05)
            prediction = (x + avg) / 2 + noise
            predictions.append(prediction)

        return predictions

    def evaluate(self, predictions):
        self.log("Evaluating predictions...")
        threshold = 0.5
        results = ["HIGH" if p > threshold else "LOW" for p in predictions]
        return results


# --- Simulation ---
if __name__ == "__main__":
    ai = SimpleAIPredictor("DemoAI")

    raw_data = [10, 20, 30, None, 40, 50]
    processed = ai.preprocess(raw_data)

    ai.train(processed)

    test_data = [15, 25, 35]
    processed_test = ai.preprocess(test_data)

    predictions = ai.predict(processed_test)
    results = ai.evaluate(predictions)

    print("\nFinal Results:")
    for i, res in enumerate(results):
        print(f"Input {test_data[i]} => {res}")
