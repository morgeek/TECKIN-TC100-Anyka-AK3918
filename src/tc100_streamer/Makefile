ZIG ?= /tmp/zig_dl/zig-macos-aarch64-0.13.0/zig
CXX = $(ZIG) c++
CXXFLAGS = -target arm-linux-musleabi -mcpu=arm926ej_s -static -fno-exceptions -fno-rtti -O3 -Wall

all: tc100_streamer

tc100_streamer: main.cpp jpge.cpp
	$(CXX) $(CXXFLAGS) -I. $^ -o $@

clean:
	rm -f tc100_streamer
