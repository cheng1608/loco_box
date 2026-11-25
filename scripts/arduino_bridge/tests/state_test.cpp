#include "../BridgeState.h"
#include <assert.h>
#include <stdio.h>

static bool down(const BridgeState& state, unsigned key) {
    return state.keys()[key / 8] & (1u << (key % 8));
}
static unsigned count(const BridgeState& state) {
    unsigned total = 0;
    for (unsigned key = 0; key < 120; ++key) total += down(state, key);
    return total;
}
int main() {
    BridgeState state;
    state.begin("song1", 100);
    assert(state.setMusic("song1", 0, 511, 110) == BridgeState::OK);
    assert(count(state) == 9);
    assert(down(state, 5) && down(state, 28) && down(state, 24));
    assert(state.setMusic("song1", 0, 511, 115) == BridgeState::OK);
    assert(state.setMusic("song1", 0, 0, 120) == BridgeState::STALE_SEQUENCE);
    assert(count(state) == 9);
    assert(state.pressKey(30, 0, 50, 120) == BridgeState::BUSY);
    assert(state.setMusic("song1", 1, 1, 130) == BridgeState::OK);
    assert(count(state) == 1 && down(state, 5));
    assert(state.setMusic("old", 3, 0, 140) == BridgeState::BAD_SESSION);
    assert(state.setMusic("song1", 0, 0, 140) == BridgeState::STALE_SEQUENCE);
    assert(state.setMusic("song1", 2, 512, 140) == BridgeState::BAD_MASK);
    assert(state.stop("old") == BridgeState::BAD_SESSION);
    assert(count(state) == 1);
    assert(state.stop("song1") == BridgeState::OK);
    assert(!state.active() && count(state) == 0);
    assert(state.setMusic("song1", 10, 511, 150) == BridgeState::BAD_SESSION);

    state.begin("new", 200);
    assert(state.setMusic("new", 0, 511, 200) == BridgeState::OK);
    assert(!state.tick(1699));
    assert(state.heartbeat("new", 1699) == BridgeState::OK);
    assert(!state.tick(3198));
    assert(state.tick(3199));
    assert(!state.active() && count(state) == 0);
    assert(state.heartbeat("new", 3200) == BridgeState::BAD_SESSION);

    // Separate legacy deadlines: a long modifier must not block a key or mouse.
    assert(state.pressKey(0, 2, 3000, 4000) == BridgeState::OK);
    assert(state.pressKey(30, 0, 50, 4001) == BridgeState::OK);
    assert(state.pressKey(58, 0, 70, 4002) == BridgeState::OK);
    assert(state.pressMouse(1, 20, 4003) == BridgeState::OK);
    assert(state.tick(4023));
    assert(state.mouse() == 0 && state.modifiers() == 2 && count(state) == 2);
    assert(state.tick(4051));
    assert(!down(state, 30) && down(state, 58) && state.modifiers() == 2);
    assert(state.tick(4072));
    assert(count(state) == 0 && state.modifiers() == 2);
    assert(state.tick(7000) && state.modifiers() == 0);
    assert(state.pressKey(30, 0, 60000, 8000) == BridgeState::OK);
    assert(state.pressMouse(3, 60000, 8000) == BridgeState::OK);
    state.panic();
    assert(count(state) == 0 && state.mouse() == 0 && state.modifiers() == 0);

    // Both deadline arithmetic and watchdog must survive millis() rollover.
    assert(state.pressKey(30, 0, 50, 0xfffffff0u) == BridgeState::OK);
    assert(!state.tick(0x21u));
    assert(state.tick(0x22u) && count(state) == 0);
    state.begin("wrap", 0xffffff00u);
    assert(state.setMusic("wrap", 0, 1, 0xffffff00u) == BridgeState::OK);
    assert(!state.tick(1243));
    assert(state.tick(1244) && count(state) == 0);

    BridgeState compat(6);
    compat.begin("six", 0);
    assert(compat.setMusic("six", 0, 63, 0) == BridgeState::OK);
    assert(compat.setMusic("six", 1, 127, 1) == BridgeState::TOO_MANY_KEYS);
    assert(count(compat) == 6);
    compat.begin("replace", 2);
    assert(count(compat) == 0);
    assert(compat.setMusic("six", 2, 1, 3) == BridgeState::BAD_SESSION);
    puts("BridgeState state, ownership, capacity, release and watchdog tests passed");
}
