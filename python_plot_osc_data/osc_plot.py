import pandas as pd
import matplotlib.pyplot as plt

# Path to your CSV file
csv_path = r"C:\Users\Aidan\OneDrive - University of Glasgow\Design Special Topic 5 - General\Lab Notes\6_05_26_trying_TIA_circuit\Data\LED_and_photodiode_first_TIA_circuit.csv"

# Read CSV
df = pd.read_csv(csv_path, skiprows=[1])

# Rename columns
df.columns = ["time", "signal", "supply"]

# Convert seconds to microseconds
df["time_us"] = df["time"] * 1e6

# Plot
plt.figure(figsize=(10, 5))

plt.plot(df["time_us"], df["signal"], label="TIA response")
plt.plot(df["time_us"], df["supply"], label="LED Pulse")

plt.xlabel("Time (µs)")
plt.ylabel("Voltage (V)")

title = "TIA circuit response to LED Pulse at 1 mm"
plt.title(title)

# Force major grid every 10 µs
plt.xticks(range(-20, 21, 10))

# Set x-axis limits to exactly the data range
plt.xlim(df["time_us"].min(), df["time_us"].max())
plt.legend()
plt.grid(True)

plt.tight_layout()
plt.savefig(f"{title}.svg", format="svg", bbox_inches="tight")
plt.savefig(f"{title}.pdf", format="pdf", bbox_inches="tight")
plt.show()