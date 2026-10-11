#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "3ds_input.h"

int main(void)
{
    CtrInput state = {0};
    CtrInputSample sample = {0};
    for (unsigned bit = 0; bit < 12; ++bit)
    {
        sample.buttons = 1u << bit;
        CtrInput_Update(&state, &sample);
        assert(state.physicalDown == sample.buttons && state.physicalUp == 0);
        assert(state.held == (sample.buttons & CTR_KEY_GAME));
        for (unsigned frame = 0; frame < 120; ++frame)
        {
            CtrInput_Update(&state, &sample);
            assert(state.physicalDown == 0 && state.down == 0);
        }
        assert(state.presses[bit] == 1);
        sample.buttons = 0;
        CtrInput_Update(&state, &sample);
        assert(state.physicalUp == (1u << bit));
        assert(state.held == 0);
    }
    sample.circleX = 39;
    CtrInput_Update(&state, &sample);
    assert(state.held == 0);
    sample.circleX = 40;
    CtrInput_Update(&state, &sample);
    assert(state.held == CTR_KEY_RIGHT && state.down == CTR_KEY_RIGHT);
    sample.circleX = 28;
    CtrInput_Update(&state, &sample);
    assert(state.held == CTR_KEY_RIGHT && !state.down);
    sample.circleX = 27;
    CtrInput_Update(&state, &sample);
    assert(!state.held && state.up == CTR_KEY_RIGHT);
    sample.circleX = 100;
    sample.circleY = 95;
    CtrInput_Update(&state, &sample);
    assert(state.held == CTR_KEY_RIGHT);
    sample.circleY = 105;
    CtrInput_Update(&state, &sample);
    assert(state.held == CTR_KEY_RIGHT); /* axis hysteresis */
    sample.circleY = 120;
    CtrInput_Update(&state, &sample);
    assert(state.held == CTR_KEY_UP);
    sample.buttons = CTR_KEY_LEFT;
    CtrInput_Update(&state, &sample);
    assert(state.held == CTR_KEY_LEFT); /* D-pad wins; no manufactured diagonal */
    sample.buttons = 0;
    for (int x = -160; x <= 160; x += 5)
        for (int y = -160; y <= 160; y += 5)
        {
            sample.circleX = x;
            sample.circleY = y;
            CtrInput_Update(&state, &sample);
            assert((state.held & (state.held - 1)) == 0); /* zero or one bit */
        }
    sample.touchActive = true;
    sample.touchX = 999;
    sample.touchY = 999;
    CtrInput_Update(&state, &sample);
    assert(state.touchDown && !state.touchUp);
    assert(state.touchX == 319 && state.touchY == 239);
    assert(state.touchNormX == 1 && state.touchNormY == 1);
    CtrInput_Update(&state, &sample);
    assert(!state.touchDown && !state.touchUp);
    sample.touchActive = false;
    CtrInput_Update(&state, &sample);
    assert(state.touchUp && !state.touchDown && state.touchX == 0 && state.touchY == 0);
    assert(state.touchNormX == 0 && state.touchNormY == 0);
    memset(&state, 0, sizeof(state)); /* same operation as resume/reset */
    memset(&sample, 0, sizeof(sample));
    CtrInput_Update(&state, &sample);
    assert(!state.held && !state.down && !state.up);
    puts("PASS input: 12 buttons/edges, hold, deadzone/hysteresis, cardinal stick, precedence, touch");
    return 0;
}
