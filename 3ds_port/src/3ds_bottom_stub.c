/*
 * The bottom screen until FireRed has its own: the Emerald port's touch UI
 * (3ds_bottom_ui.c) drives Emerald's menus and is left out of this build.
 * The keys pass through untouched and nothing is drawn below.
 */
#include <stdint.h>
#include "3ds_bottom.h"

void CtrBottom_Init(void) {}
void CtrBottom_Frame(void) {}
uint16_t CtrBottom_InjectedKeys(void) { return 0; }
uint16_t CtrBottom_FilterKeys(uint16_t held) { return held; }
