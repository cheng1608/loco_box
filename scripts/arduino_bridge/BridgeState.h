#ifndef LOCOBOX_BRIDGE_STATE_H
#define LOCOBOX_BRIDGE_STATE_H
#include <stdint.h>
#include <string.h>

// Portable state machine: every keyboard path owns this single report state.
class BridgeState {
public:
    enum Result { OK, BAD_SESSION, STALE_SEQUENCE, BAD_MASK, TOO_MANY_KEYS, BUSY };
    static const uint8_t KEY_BYTES = 15;
    static const uint16_t WATCHDOG_MS = 1500;
    explicit BridgeState(uint8_t maxKeys = 9) : maxKeys_(maxKeys) { panic(); }
    void panic() {
        memset(keys_, 0, sizeof(keys_)); memset(timed_, 0, sizeof(timed_));
        memset(keyDue_, 0, sizeof(keyDue_)); memset(modDue_, 0, sizeof(modDue_));
        memset(mouseDue_, 0, sizeof(mouseDue_));
        modifiers_ = mouse_ = 0; session_[0] = 0; hasSequence_ = false;
        sequence_ = 0; mask_ = 0; lastSeen_ = 0;
    }
    bool active() const { return session_[0] != 0; }
    uint8_t maxKeys() const { return maxKeys_; }
    const uint8_t* keys() const { return keys_; }
    uint8_t modifiers() const { return modifiers_; }
    uint8_t mouse() const { return mouse_; }
    uint32_t sequence() const { return sequence_; }
    void begin(const char* session, uint32_t now) {
        if (active() && strcmp(session_, session) == 0) { lastSeen_ = now; return; }
        panic(); strncpy(session_, session, sizeof(session_) - 1);
        session_[sizeof(session_) - 1] = 0; lastSeen_ = now;
    }
    Result setMusic(const char* session, uint32_t sequence, uint16_t mask, uint32_t now) {
        if (!matches(session)) return BAD_SESSION;
        if (mask & ~0x1FFu) return BAD_MASK;
        if (hasSequence_ && (sequence < sequence_ || (sequence == sequence_ && mask != mask_))) return STALE_SEQUENCE;
        if (popcount(mask) > maxKeys_) return TOO_MANY_KEYS;
        static const uint8_t musicKeys[9] = {5, 9, 10, 11, 13, 14, 23, 28, 24}; // B F G H J K T Y U
        memset(keys_, 0, sizeof(keys_));
        for (uint8_t i = 0; i < 9; ++i) if (mask & (1u << i)) set(keys_, musicKeys[i], true);
        mask_ = mask; sequence_ = sequence; hasSequence_ = true; lastSeen_ = now;
        return OK;
    }
    Result heartbeat(const char* session, uint32_t now) {
        if (!matches(session)) return BAD_SESSION;
        lastSeen_ = now; return OK;
    }
    Result stop(const char* session) {
        if (!matches(session)) return BAD_SESSION;
        panic(); return OK;
    }
    Result pressKey(uint8_t key, uint8_t modifier, uint16_t duration, uint32_t now) {
        if (active()) return BUSY;
        if (key >= KEY_BYTES * 8) return BAD_MASK;
        if (key && !get(keys_, key) && keyCount() >= maxKeys_) return TOO_MANY_KEYS;
        const uint32_t due = now + (duration ? duration : 1);
        if (key) { set(keys_, key, true); set(timed_, key, true); keyDue_[key] = due; }
        for (uint8_t i = 0; i < 8; ++i) if (modifier & (1u << i)) { modifiers_ |= 1u << i; modDue_[i] = due; }
        return OK;
    }
    Result pressMouse(uint8_t buttons, uint16_t duration, uint32_t now) {
        if (active()) return BUSY;
        for (uint8_t i = 0; i < 3; ++i) if (buttons & (1u << i)) {
            mouse_ |= 1u << i; mouseDue_[i] = now + (duration ? duration : 1);
        }
        return OK;
    }
    bool tick(uint32_t now) {
        if (active()) {
            if (uint32_t(now - lastSeen_) >= WATCHDOG_MS) { panic(); return true; }
            return false;
        }
        bool changed = false;
        for (uint8_t key = 1; key < KEY_BYTES * 8; ++key) {
            if (get(timed_, key) && int32_t(now - keyDue_[key]) >= 0) {
                set(keys_, key, false); set(timed_, key, false); changed = true;
            }
        }
        for (uint8_t i = 0; i < 8; ++i) if ((modifiers_ & (1u << i)) && int32_t(now - modDue_[i]) >= 0) {
            modifiers_ &= ~(1u << i); changed = true;
        }
        for (uint8_t i = 0; i < 3; ++i) if ((mouse_ & (1u << i)) && int32_t(now - mouseDue_[i]) >= 0) {
            mouse_ &= ~(1u << i); changed = true;
        }
        return changed;
    }
private:
    uint8_t maxKeys_, keys_[KEY_BYTES], timed_[KEY_BYTES];
    uint32_t keyDue_[KEY_BYTES * 8], modDue_[8], mouseDue_[3];
    uint8_t modifiers_, mouse_;
    char session_[33];
    uint32_t sequence_, lastSeen_;
    uint16_t mask_;
    bool hasSequence_;
    bool matches(const char* session) const { return active() && strcmp(session_, session) == 0; }
    static bool get(const uint8_t* bits, uint8_t key) { return bits[key / 8] & (1u << (key % 8)); }
    static void set(uint8_t* bits, uint8_t key, bool pressed) {
        if (pressed) bits[key / 8] |= 1u << (key % 8);
        else bits[key / 8] &= ~(1u << (key % 8));
    }
    static uint8_t popcount(uint16_t value) {
        uint8_t count = 0;
        while (value) { count += value & 1u; value >>= 1; }
        return count;
    }
    uint8_t keyCount() const {
        uint8_t count = 0;
        for (uint8_t i = 0; i < KEY_BYTES; ++i) count += popcount(keys_[i]);
        return count;
    }
};
#endif
