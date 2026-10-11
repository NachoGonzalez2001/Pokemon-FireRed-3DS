# HOME Menu forwarder: a small CIA that starts sdmc:/3ds/emerald3ds/Emerald3DS.3dsx
# through Luma3DS's hb:ldr, so updates only replace the 3DSX.
#
#   make -C 3ds_port/forwarder            -> dist/Emerald3DS-Forwarder.cia
#
# Needs devkitARM + libctru, makerom and bannertool (on PATH, in ../tools-bin,
# or given as MAKEROM= / BANNERTOOL=).
.SUFFIXES:
DEVKITPRO ?= /opt/devkitpro
DEVKITARM ?= $(DEVKITPRO)/devkitARM
CTRULIB := $(DEVKITPRO)/libctru
CC := $(DEVKITARM)/bin/arm-none-eabi-gcc
ARCH := -march=armv6k -mtune=mpcore -mfloat-abi=hard -mtp=soft
CFLAGS := $(ARCH) -O2 -Wall -Wextra -Werror -ffunction-sections -fdata-sections -D__3DS__ -I$(CTRULIB)/include
LDFLAGS := $(ARCH) -specs=3dsx.specs -Wl,--gc-sections -L$(CTRULIB)/lib
LIBS := -lctru -lm

TOOLS_BIN := $(abspath ../tools-bin)
EXE := $(if $(filter Windows_NT,$(OS)),.exe,)
MAKEROM ?= $(firstword $(wildcard $(TOOLS_BIN)/makerom$(EXE)) makerom)
BANNERTOOL ?= $(firstword $(wildcard $(TOOLS_BIN)/bannertool$(EXE)) bannertool)

ART := ../assets/artwork
APP_TITLE := Pokemon Emerald 3Ds Dual Screen
APP_SHORT := Emerald 3Ds Dual Screen
APP_AUTHOR := ZallaxDev
# Shown by FBI and the HOME Menu; bump with the forwarder, not with the game.
APP_VERSION ?= 1.0.0
CIA := dist/Emerald3DS-Forwarder.cia

all: $(CIA)

build/forwarder.elf: source/main.c Makefile
	@mkdir -p build
	$(CC) $(CFLAGS) $(LDFLAGS) $< $(LIBS) -o $@

build/banner.bnr: $(ART)/banner.png $(ART)/banner-sound.wav
	@mkdir -p build
	$(BANNERTOOL) makebanner -i $(ART)/banner.png -a $(ART)/banner-sound.wav -o $@

build/icon.smdh: $(ART)/icon.png Makefile
	@mkdir -p build
	$(BANNERTOOL) makesmdh -s "$(APP_SHORT)" -l "$(APP_TITLE)" -p "$(APP_AUTHOR)" -i $(ART)/icon.png -o $@

$(CIA): build/forwarder.elf build/banner.bnr build/icon.smdh forwarder.rsf
	@mkdir -p dist
	$(MAKEROM) -f cia -o $@ -target t -exefslogo -rsf forwarder.rsf -elf build/forwarder.elf \
		-banner build/banner.bnr -icon build/icon.smdh \
		-major $(word 1,$(subst ., ,$(APP_VERSION))) -minor $(word 2,$(subst ., ,$(APP_VERSION))) \
		-micro $(word 3,$(subst ., ,$(APP_VERSION)))

clean:
	rm -rf build dist

.PHONY: all clean
