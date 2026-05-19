import pandas as pd
import matplotlib.pyplot as plt

# Path to your CSV file
csv_path = r"C:\Users\Aidan\OneDrive - University of Glasgow\Design Special Topic 5 - General\Lab Notes\6_05_26_trying_TIA_circuit\Data\LED_and_photodiode_first_TIA_circuit.csv"

# Read CSV
# The second row contains units, so we skip it
df = pd.read_csv(csv_path, skiprows=[1])

# Rename columns to something cleaner
df.columns = ["time", "signal", "supply"]

# Plot
plt.figure(figsize=(10, 5))

plt.plot(df["time"], df["signal"], label="Signal")
plt.plot(df["time"], df["supply"], label="Supply")

plt.xlabel("Time (s)")
plt.ylabel("Voltage (V)")
plt.title("CSV Data Plot")
plt.legend()
plt.grid(True)

plt.tight_layout()
plt.show()

# Save dataframe back to CSV
output_path = "output.csv"

df.to_csv(output_path, index=False)