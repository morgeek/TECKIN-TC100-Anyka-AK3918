import wave
import struct
import os

def generate_pcm(filename, duration_sec=1.0, freq=440, sample_rate=8000):
    # Generates a simple sine wave at 8000Hz, 16-bit Mono
    num_samples = int(duration_sec * sample_rate)
    
    # Ensure directory exists
    os.makedirs(os.path.dirname(filename), exist_ok=True)
    
    with open(filename, 'wb') as f:
        for i in range(num_samples):
            import math
            # Sine wave value between -32767 and 32767
            value = int(32767 * math.sin(2.0 * math.pi * freq * i / sample_rate))
            # Pack as 16-bit signed integer (little-endian)
            f.write(struct.pack('<h', value))

if __name__ == "__main__":
    # Success sound: double beep
    generate_pcm("sounds/startup.pcm", duration_sec=0.2, freq=800)
    generate_pcm("sounds/startup_2.pcm", duration_sec=0.2, freq=1200)
    
    # Combined sound file for startup
    with open("sounds/startup_complete.pcm", "wb") as outfile:
        for f in ["sounds/startup.pcm", "sounds/startup_2.pcm"]:
            with open(f, "rb") as infile:
                outfile.write(infile.read())
    
    # Motion detected: lower tone alert
    generate_pcm("sounds/alert.pcm", duration_sec=0.5, freq=400)
    
    print("Generated PCM files in sounds/ directory.")
