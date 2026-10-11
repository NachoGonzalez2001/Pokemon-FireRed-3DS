#ifndef GUARD_PORT_AUDIO_PROTOCOL_COMPAT_H
#define GUARD_PORT_AUDIO_PROTOCOL_COMPAT_H

/* Player-intent encoding m4a.c uses to describe song and player commands. The
 * ARM11 backend consumes it directly; there is no inter-processor transport. */

enum PortAudioCommand
{
    PORT_AUDIO_CMD_SONG_START = 2,
    PORT_AUDIO_CMD_SET_SONGTABLE = 3,
    PORT_AUDIO_CMD_SET_DEBUG = 4,
    PORT_AUDIO_CMD_PLAYER_STOP = 5,
    PORT_AUDIO_CMD_PLAYER_CONTINUE = 6,
    PORT_AUDIO_CMD_FADE_OUT = 7,
    PORT_AUDIO_CMD_FADE_OUT_TEMP = 8,
    PORT_AUDIO_CMD_FADE_IN = 9,
    PORT_AUDIO_CMD_VOLUME_ALL = 10,
    PORT_AUDIO_CMD_TEMPO = 11,
    PORT_AUDIO_CMD_PITCH_ALL = 12,
    PORT_AUDIO_CMD_PAN_ALL = 13,
    PORT_AUDIO_CMD_IMM_INIT = 14,
    PORT_AUDIO_CMD_ALL_STOP = 15,
};

enum PortAudioStartMode
{
    PORT_AUDIO_START_ALWAYS,
    PORT_AUDIO_START_OR_CHANGE,
    PORT_AUDIO_START_OR_CONTINUE,
};

#define PORT_AUDIO_COMMAND(data) ((data) & 0xF)
#define PORT_AUDIO_PLAYER(data) (((data) >> 4) & 3)
#define PORT_AUDIO_VALUE(data) ((data) >> 6)
#define PORT_AUDIO_SONG(data) (((data) >> 4) & 0x3FF)
#define PORT_AUDIO_START_MODE(data) (((data) >> 14) & 3)

#endif
