# The whole FireRed tree for ARM11, with resources outside the executable.
#
# Adapted from the Emerald 3DS port's full.mk (MIT, see NOTICE.md).
#
# Graphics and map payloads leave the executable through link-time stubs and
# are resolved at runtime (3ds_assets.c, 3ds_map_loader.c); script bytecode and
# MP2K song data, whose pointers sit at unaligned offsets, are bundled into
# reserved regions and relocated at load (scripts/ctr_bundle.py). Map headers,
# the asset index and the sound bank stay resident.
#
# Game translation units are built in ARM state, like the native backend: GCC
# has no Thumb-1 hard-float VFP ABI on ARMv6K, and libctru is hard-float.

PREPROC := $(abspath $(ROOT)/tools/preproc/preproc$(EXESUFFIX))
MAPJSON := $(abspath $(ROOT)/tools/mapjson/mapjson$(EXESUFFIX))
WAV2AGB := $(abspath $(ROOT)/tools/wav2agb/wav2agb$(EXESUFFIX))
GAME_ARCH := $(ARCH)
ASM_PSEUDO_OP_CONV := sed -e 's/\.4byte/\.int/g;s/\.2byte/\.short/g'
AS := $(DEVKITARM)/bin/arm-none-eabi-as
CPPTOOL := $(DEVKITARM)/bin/arm-none-eabi-cpp
# pokefirered's own data preprocessing flags (its Makefile's $(CPP) line)
CPPTOOL_FLAGS := -nostdinc -undef -Wno-unicode
ASFLAGS := -mcpu=mpcore --defsym MODERN=1 --defsym PORTABLE=1 --defsym UBFIX=1 -I$(ROOT)
ASFLAGS += --defsym $(GAME_VERSION)=1 --defsym REVISION=$(GAME_REVISION) --defsym $(GAME_LANGUAGE)=1

# Game translation units see the port bridge (compat/port_platform.h): the
# hooks in the shared tree that route resources, scripts and saves to the
# ARM11 backend are compiled in with PORT_BRIDGE.
BRIDGE_FLAGS := -DPORT_BRIDGE

# The compile runs from the repository root (preproc resolves charmap and
# include paths there), so every search path is absolute.
FULL_INCLUDES := -iquote $(abspath compat) -iquote $(abspath include) -iquote $(abspath $(ROOT)/include)
FULL_INCLUDES += -iquote $(abspath $(ROOT)/include/constants) -iquote $(abspath $(ROOT))
FULLFLAGS := $(filter-out -iquote include -iquote ../include -iquote ../include/constants -iquote ..,$(GAMEFLAGS)) $(FULL_INCLUDES) $(BRIDGE_FLAGS)
FULLCFLAGS := $(GAME_ARCH) $(filter-out $(ARCH),$(GAMECFLAGS))

ROOT_C_SRCS := $(wildcard $(ROOT)/src/*.c $(ROOT)/src/*/*.c $(ROOT)/src/*/*/*.c)
# *.inc.c are included by other units, as pokefirered's Makefile skips them.
ROOT_C_SRCS := $(foreach src,$(ROOT_C_SRCS),$(if $(findstring .inc.c,$(src)),,$(src)))
# GBA-only programs; 3ds_compat.c provides their entry points. isagbprn.c is
# the AGBPrint debug-unit library, ARM7 inline assembly; portable builds
# define NDEBUG (include/config.h) so nothing calls it.
ROOT_C_SRCS := $(filter-out $(ROOT)/src/berry_fix_program.c $(ROOT)/src/isagbprn.c,$(ROOT_C_SRCS))

ROOT_DATA_SRCS := $(wildcard $(ROOT)/data/*.s)
ROOT_DATA_SRCS := $(filter-out $(ROOT)/data/multiboot_berry_glitch_fix.s $(ROOT)/data/multiboot_ereader.s \
	$(ROOT)/data/multiboot_pokemon_colosseum.s,$(ROOT_DATA_SRCS))
# maps.s is regenerated with externalised layout payloads.
ROOT_DATA_SRCS := $(filter-out $(ROOT)/data/maps.s,$(ROOT_DATA_SRCS))
# Script sections are assembled but not linked: their pointers are unaligned,
# so they move to RomFS and land in a reserved region (gen_script_bundle.py).
SCRIPT_DATA_SRCS := battle_ai_scripts battle_anim_scripts battle_scripts_1 battle_scripts_2 \
	event_scripts field_effect_scripts
SCRIPT_DATA_OBJS := $(patsubst %,build/root/data/%.o,$(SCRIPT_DATA_SRCS))
ROOT_DATA_SRCS := $(filter-out $(patsubst %,$(ROOT)/data/%.s,$(SCRIPT_DATA_SRCS)),$(ROOT_DATA_SRCS))

# Voice groups, the song table and the samples come from data/sound_data.s; the
# song headers themselves are one object per tune, referenced from that table.
ROOT_MID_SRCS := $(patsubst %.mid,%.s,$(wildcard $(ROOT)/sound/songs/midi/*.mid))
ROOT_SONG_SRCS := $(wildcard $(ROOT)/sound/songs/*.s) $(ROOT_MID_SRCS)
ROOT_SONG_OBJS := $(patsubst $(ROOT)/%.s,build/root/%.o,$(ROOT_SONG_SRCS))
ROOT_SOUND_WAV_SRCS := $(wildcard $(ROOT)/sound/direct_sound_samples/*.wav $(ROOT)/sound/direct_sound_samples/*/*.wav)
ROOT_SOUND_BIN_SRCS := $(patsubst %.wav,%.bin,$(ROOT_SOUND_WAV_SRCS))

FULL_C_OBJS := $(patsubst $(ROOT)/%.c,build/root/%.o,$(ROOT_C_SRCS))
FULL_DATA_OBJS := $(patsubst $(ROOT)/%.s,build/root/%.o,$(ROOT_DATA_SRCS)) build/root/data/maps.o
FULL_DATA_OBJS += build/root/3ds_script_blob.o build/root/3ds_script_keep.o
# The song objects are assembled but not linked, for the same reason the script
# sections are not: a PATT command puts a 32-bit pointer at whatever offset the
# preceding bytes leave it on, and 3dsxtool rejects unaligned relocations.
FULL_DATA_OBJS += build/root/3ds_song_blob.o
BACKEND_SRCS := src/3ds_assets.c src/3ds_map_loader.c src/3ds_compat.c
BACKEND_SRCS += src/3ds_game_full.c src/3ds_game_bridge.c src/3ds_script_loader.c
# Nothing on the bottom screen yet (the Emerald touch UI is left out).
BACKEND_SRCS += src/3ds_bottom_stub.c
# The frame profiler times the engine's own routines through linker wrappers.
BACKEND_SRCS += src/3ds_prof_wrap.c
PROF_WRAPPED := RunTasks AnimateSprites BuildOamBuffer ProcessDma3Requests \
	LZ77UnCompWram LZ77UnCompVram RLUnCompWram RLUnCompVram CpuSet CpuFastSet DmaSet UpdatePaletteFade
# The sound engine runs on a worker core; its entry points take the worker's
# lock (src/3ds_sound.c).
BACKEND_SRCS += src/3ds_sound.c
SOUND_WRAPPED := m4aSoundVSync m4aSoundMain m4aSoundInit m4aSoundMode m4aSoundVSyncOn m4aSoundVSyncOff \
	m4aSongNumStart m4aSongNumStartOrChange m4aSongNumStartOrContinue m4aSongNumStop m4aSongNumContinue \
	m4aMPlayAllStop m4aMPlayAllContinue m4aMPlayStop m4aMPlayContinue m4aMPlayFadeOut \
	m4aMPlayFadeOutTemporarily m4aMPlayFadeIn m4aMPlayImmInit m4aMPlayTempoControl \
	m4aMPlayVolumeControl m4aMPlayPitchControl m4aMPlayPanpotControl m4aMPlayModDepthSet \
	m4aMPlayLFOSpeedSet MPlayStart MPlayContinue MPlayFadeOut SetPokemonCryVolume \
	SetPokemonCryPanpot SetPokemonCryPitch SetPokemonCryLength SetPokemonCryRelease \
	SetPokemonCryProgress SetPokemonCryChorus SetPokemonCryStereo SetPokemonCryPriority \
	SetPokemonCryTone IsPokemonCryPlaying
LDFLAGS += $(foreach f,$(PROF_WRAPPED) $(SOUND_WRAPPED),-Wl,--wrap=$(f))
BACKEND_OBJS := $(patsubst src/%.c,build/bridge/%.o,$(BACKEND_SRCS))

FULL_OBJECTS := $(FULL_C_OBJS) $(FULL_DATA_OBJS) $(BACKEND_OBJS)
# The keep table is only referenced from the payload, which is not linked,
# so it has to be a garbage-collection root or it takes the handlers with it.
LDFLAGS += -Wl,--undefined=__ctr_script_keep

ROMFS_ASSET_OUTS := romfs/assets/asset_index.bin romfs/assets/asset_map.txt \
	romfs/assets/asset_ptr_index.bin romfs/assets/asset_ptr_map.txt
ROMFS_MAP_OUT := romfs/maps/layouts.bin
ROMFS_SCRIPT_OUTS := romfs/scripts/scripts.bin romfs/scripts/scripts.rel
ROMFS_SOUND_OUTS := romfs/sound/songs.bin romfs/sound/songs.rel
ROMFS_GAMEDATA_OUTS := romfs/gamedata/gamedata.bin romfs/gamedata/gamedata.rel
ROMFS_SHADER_OUTS :=

$(FULL_OBJECTS): build/config

# Every game C unit, for compiling them alone (make game-objs -k): the first
# milestone of a port is the game compiling, before anything links.
.PHONY: game-objs data-objs
game-objs: $(FULL_C_OBJS)
# Every assembled data unit: tables, maps, the script sections and the songs.
data-objs: $(patsubst $(ROOT)/%.s,build/root/%.o,$(ROOT_DATA_SRCS)) build/root/data/maps.o \
	$(SCRIPT_DATA_OBJS) $(ROOT_SONG_OBJS)

# The platform layer's scanline renderer draws every frame (3ds_game_full.c).
build/root/src/platform/gba_fast_draw.o: FULLCFLAGS += -DRENDERER_FAST_DRAW -O3

build/root/%.o: $(ROOT)/%.c Makefile full.mk
	@mkdir -p $(dir $@)
	cd $(ROOT) && "$(CC)" $(FULLFLAGS) $(FULLCFLAGS) -E -x c $(patsubst $(ROOT)/%,%,$<) \
		| "$(PREPROC)" -i $(patsubst $(ROOT)/%,%,$<) charmap.txt \
		| "$(CC)" $(FULLFLAGS) $(FULLCFLAGS) -x c -c -o $(CURDIR)/$@ -

build/root/data/maps.o: build/maps.s build/map_layouts.inc $(ROOT)/data/layouts/layouts_table.inc \
		$(ROOT)/data/maps/headers.inc $(ROOT)/data/maps/groups.inc $(ROOT)/data/maps/connections.inc
	@mkdir -p $(dir $@)
	cd $(ROOT) && "$(PREPROC)" 3ds_port/build/maps.s charmap.txt | "$(CPPTOOL)" $(CPPTOOL_FLAGS) -Iinclude -I. - \
		| "$(PREPROC)" -ie 3ds_port/build/maps.s charmap.txt | $(ASM_PSEUDO_OP_CONV) - \
		| "$(AS)" $(ASFLAGS) -o $(CURDIR)/$@

build/root/data/%.o: $(ROOT)/data/%.s Makefile full.mk
	@mkdir -p $(dir $@)
	cd $(ROOT) && "$(PREPROC)" data/$*.s charmap.txt | "$(CPPTOOL)" $(CPPTOOL_FLAGS) -Iinclude -I. - \
		| "$(PREPROC)" -ie data/$*.s charmap.txt | $(ASM_PSEUDO_OP_CONV) - \
		| "$(AS)" $(ASFLAGS) -o $(CURDIR)/$@

# The samples are .incbin'd from paths relative to the repository root, and the
# generic data rule already assembles from there. Only the dependency is new.
build/root/data/sound_data.o: $(ROOT_SOUND_BIN_SRCS)

build/root/sound/songs/%.o: $(ROOT)/sound/songs/%.s
	@mkdir -p $(dir $@)
	$(ASM_PSEUDO_OP_CONV) $< | "$(AS)" $(ASFLAGS) -I$(ROOT)/sound -o $@

# mid2agb takes per-song options from sound/songs/midi/midi.cfg, which the root
# Makefile already parses: the conversion is delegated to it, in one call.
ROOT_MID_DEPS := $(wildcard $(ROOT)/sound/songs/midi/*.mid) $(ROOT)/sound/songs/midi/midi.cfg
build/midi.stamp: $(ROOT_MID_DEPS)
	+$(MAKE) -C $(ROOT) $(patsubst $(ROOT)/%,%,$(ROOT_MID_SRCS))
	@mkdir -p build
	@touch $@
$(ROOT_MID_SRCS): build/midi.stamp ;
.SECONDARY: $(ROOT_MID_SRCS)

# Per-map header/events/connections includes, generated by mapjson for any map
# that does not have them yet (a fresh upstream tree has none).
build/map_includes.stamp: $(wildcard $(ROOT)/data/maps/*/map.json) $(ROOT)/data/layouts/layouts.json
	"$(PYTHON)" $(SCRIPTS)/gen_missing_map_includes.py
	@mkdir -p build
	@touch $@
build/root/data/map_events.o build/root/data/maps.o: build/map_includes.stamp

# Sample conversion, with the flags the root audio_rules.mk uses.
$(WAV2AGB): $(wildcard $(ROOT)/tools/wav2agb/*.cpp $(ROOT)/tools/wav2agb/*.h)
	$(MAKE) -C $(ROOT)/tools/wav2agb

$(ROOT)/sound/direct_sound_samples/cries/%.bin: $(ROOT)/sound/direct_sound_samples/cries/%.wav | $(WAV2AGB)
	"$(WAV2AGB)" -b -c -l 1 --no-pad $< $@

$(ROOT)/sound/direct_sound_samples/%.bin: $(ROOT)/sound/direct_sound_samples/%.wav | $(WAV2AGB)
	"$(WAV2AGB)" -b $< $@

build/root/data/map_events.o: $(ROOT)/data/map_events.s $(ROOT)/data/maps/events.inc
build/root/data/event_scripts.o: $(ROOT)/data/script_cmd_table.inc $(ROOT)/data/specials.inc
build/root/data/battle_anim_scripts.o: $(ROOT)/asm/macros/battle_anim_script.inc $(ROOT)/include/constants/battle_anim.h

# The backend's bridge units see game headers but allocate from the C library
# (FireRed's malloc.h renames malloc/free to the game heap's Alloc/Free).
build/bridge/%.o: src/%.c Makefile full.mk include/3ds_assets.h compat/port_platform.h
	@mkdir -p $(dir $@)
	"$(CC)" $(FULLFLAGS) $(FULLCFLAGS) -DCTR_NATIVE_MALLOC -MMD -MP -c $< -o $@

build/maps.s build/map_layouts.inc $(ROMFS_MAP_OUT) &: $(SCRIPTS)/gen_map_data.py \
		$(ROOT)/data/maps.s $(ROOT)/data/layouts/layouts.inc
	@mkdir -p build romfs/maps
	"$(PYTHON)" $(SCRIPTS)/gen_map_data.py --port-dir . --fs-dir romfs

# The asset index maps the linker's INCBIN stub addresses to RomFS files, so it
# is generated from the finished ELF and does not feed back into the link.
$(ROMFS_ASSET_OUTS) &: $(TARGET).elf $(SCRIPTS)/gen_asset_table.py
	@mkdir -p romfs/assets
	"$(PYTHON)" $(SCRIPTS)/gen_asset_table.py --port-dir . --map build/$(TARGET).map \
		--fs-dir romfs --uri-prefix ""
	"$(PYTHON)" scripts/verify_assets.py --fs-dir romfs

# The reserved region must exist before the link; the payload needs the link.
build/3ds_script_blob.s build/3ds_script_keep.s &: $(SCRIPT_DATA_OBJS) scripts/gen_script_bundle.py \
		scripts/ctr_bundle.py
	"$(PYTHON)" scripts/gen_script_bundle.py --port-dir . --blob

build/3ds_song_blob.s: $(ROOT_SONG_OBJS) scripts/gen_sound_bundle.py scripts/ctr_bundle.py
	"$(PYTHON)" scripts/gen_sound_bundle.py --port-dir . --blob

build/root/3ds_script_%.o: build/3ds_script_%.s
	@mkdir -p $(dir $@)
	"$(AS)" $(ASFLAGS) -o $@ $<

build/root/3ds_song_blob.o: build/3ds_song_blob.s
	@mkdir -p $(dir $@)
	"$(AS)" $(ASFLAGS) -o $@ $<

$(ROMFS_SCRIPT_OUTS) &: $(TARGET).elf $(SCRIPT_DATA_OBJS) scripts/gen_script_bundle.py
	@mkdir -p romfs/scripts
	"$(PYTHON)" scripts/gen_script_bundle.py --port-dir . --bundle --out-dir romfs/scripts
	"$(PYTHON)" scripts/verify_scripts.py --elf $(TARGET).elf --out-dir romfs/scripts

$(ROMFS_SOUND_OUTS) &: $(TARGET).elf $(ROOT_SONG_OBJS) scripts/gen_sound_bundle.py
	@mkdir -p romfs/sound
	"$(PYTHON)" scripts/gen_sound_bundle.py --port-dir . --bundle --out-dir romfs/sound
	"$(PYTHON)" scripts/verify_scripts.py --elf $(TARGET).elf --out-dir romfs/sound \
		--tag verify_songs --magic C3AB --payload songs.bin --reloc songs.rel \
		--blob-symbol __ctr_song_blob --require mus_dummy --require mus_pallet

# The game's linked read-only data: identical layout in both links, contents
# from the image, reserved NOLOAD in the executable.
$(ROMFS_GAMEDATA_OUTS) &: build/gamedata_image.elf $(TARGET).elf scripts/gen_gamedata_bundle.py scripts/ctr_bundle.py
	"$(PYTHON)" scripts/gen_gamedata_bundle.py --image build/gamedata_image.elf --elf $(TARGET).elf \
		--out-dir romfs/gamedata

$(MAPJSON): $(wildcard $(ROOT)/tools/mapjson/*.cpp $(ROOT)/tools/mapjson/*.h)
	$(MAKE) -C $(ROOT)/tools/mapjson

.PHONY: map-includes
map-includes:
	"$(PYTHON)" $(SCRIPTS)/gen_missing_map_includes.py

-include $(BACKEND_OBJS:.o=.d)
