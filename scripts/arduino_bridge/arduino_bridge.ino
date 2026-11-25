// Open this .ino directly in Arduino IDE; keep BridgeState.h in the same folder.
// BridgeState.h contains the state-machine class, NOT another copy of this sketch.
#include <Arduino.h>
#include <HID.h>
#include <Mouse.h>
#include <ctype.h>
#include <stdlib.h>
#include "BridgeState.h"

// Compile with -DLOCOBOX_6KRO=1 for a six-key compatibility report.
#ifndef LOCOBOX_6KRO
#define LOCOBOX_6KRO 0
#endif
static const uint8_t MAX_KEYS = LOCOBOX_6KRO ? 6 : 9;
static const uint8_t KEYBOARD_REPORT_ID = 2; // Mouse is report 1.
static const uint8_t keyboardDescriptor[] PROGMEM = {
    0x05,0x01, 0x09,0x06, 0xA1,0x01, 0x85,KEYBOARD_REPORT_ID,
    0x05,0x07, 0x19,0xE0, 0x29,0xE7, 0x15,0x00, 0x25,0x01,
    0x75,0x01, 0x95,0x08, 0x81,0x02,
#if LOCOBOX_6KRO
    0x75,0x08, 0x95,0x01, 0x81,0x03,
    0x15,0x00, 0x25,0x77, 0x19,0x00, 0x29,0x77,
    0x75,0x08, 0x95,0x06, 0x81,0x00,
#else
    // Independent keyboard usages 0..119, 15 bytes plus modifiers.
    0x19,0x00, 0x29,0x77, 0x75,0x01, 0x95,0x78, 0x81,0x02,
#endif
    0xC0,
};
class ReportRegistration {
public:
    ReportRegistration() {
        static HIDSubDescriptor descriptor(keyboardDescriptor, sizeof(keyboardDescriptor));
        HID().AppendDescriptor(&descriptor);
    }
} reportRegistration;
BridgeState state(MAX_KEYS);
static char input[96];
static uint8_t inputLength = 0;
static bool inputOverflow = false;

void sendState() {
#if LOCOBOX_6KRO
    uint8_t report[8] = {state.modifiers(),0,0,0,0,0,0,0};
    uint8_t slot = 2;
    for (uint8_t key = 1; key < BridgeState::KEY_BYTES * 8 && slot < sizeof(report); ++key)
        if (state.keys()[key / 8] & (1u << (key % 8))) report[slot++] = key;
#else
    uint8_t report[1 + BridgeState::KEY_BYTES];
    report[0] = state.modifiers();
    memcpy(report + 1, state.keys(), BridgeState::KEY_BYTES);
#endif
    HID().SendReport(KEYBOARD_REPORT_ID, report, sizeof(report));
    Mouse.release((~state.mouse()) & (MOUSE_LEFT | MOUSE_RIGHT | MOUSE_MIDDLE));
    Mouse.press(state.mouse());
}
void error(const __FlashStringHelper* reason) {
    Serial.print(F("ERR ")); Serial.println(reason);
}
bool validSession(const char* value) {
    if (!value || !*value || strlen(value) > 32) return false;
    for (const char* p = value; *p; ++p)
        if (!isalnum((unsigned char)*p) && *p != '_' && *p != '-') return false;
    return true;
}
bool number(const char* value, uint32_t maximum, uint32_t& result) {
    if (!value || !*value) return false;
    result = 0;
    for (const char* p = value; *p; ++p) {
        if (*p < '0' || *p > '9') return false;
        const uint8_t digit = *p - '0';
        if (result > maximum / 10 || (result == maximum / 10 && digit > maximum % 10)) return false;
        result = result * 10 + digit;
    }
    return true;
}
void reportError(BridgeState::Result result) {
    switch (result) {
        case BridgeState::BAD_SESSION: error(F("SESSION")); break;
        case BridgeState::STALE_SEQUENCE: error(F("SEQUENCE")); break;
        case BridgeState::TOO_MANY_KEYS: error(F("CAPACITY")); break;
        case BridgeState::BUSY: error(F("BUSY")); break;
        default: error(F("ARGUMENT")); break;
    }
}
void legacy(char* command, uint32_t now) {
    uint32_t duration = 0;
    char* colon = strchr(command, ':');
    if (colon) {
        *colon = 0;
        if (!number(colon + 1, 60000, duration)) { error(F("DURATION")); return; }
    }
    for (char* p = command; *p; ++p) *p = toupper((unsigned char)*p);
    uint8_t key = 0, modifier = 0;
    if (command[0] && !command[1]) {
        const char c = command[0];
        if (c >= 'A' && c <= 'Z') key = c - 'A' + 4;
        else if (c >= '1' && c <= '9') key = c - '1' + 30;
        else if (c == '0') key = 39;
    } else {
        struct NamedKey { const char* name; uint8_t key, modifier; };
        static const NamedKey names[] = {
            {"ENTER",40,0}, {"ESC",41,0}, {"TAB",43,0}, {"SPACE",44,0},
            {"RIGHT",79,0}, {"LEFT",80,0}, {"DOWN",81,0}, {"UP",82,0},
            {"LCTRL",0,1}, {"LSHIFT",0,2}, {"RCTRL",0,16}, {"RSHIFT",0,32},
        };
        for (uint8_t i = 0; i < sizeof(names) / sizeof(names[0]); ++i)
            if (!strcmp(command, names[i].name)) { key = names[i].key; modifier = names[i].modifier; break; }
        uint32_t fn = 0;
        if (!key && !modifier && command[0] == 'F' && number(command + 1, 12, fn) && fn) key = 57 + fn;
    }
    BridgeState::Result result;
    if (!strcmp(command, "MOUSE_LEFT") || !strcmp(command, "MOUSE_RIGHT"))
        result = state.pressMouse(!strcmp(command, "MOUSE_LEFT") ? MOUSE_LEFT : MOUSE_RIGHT, duration, now);
    else if (key || modifier) result = state.pressKey(key, modifier, duration, now);
    else { error(F("COMMAND")); return; }
    if (result == BridgeState::OK) sendState();
    else reportError(result);
}
void execute(char* line) {
    const uint32_t now = millis();
    char* context = 0;
    char* command = strtok_r(line, " ", &context);
    if (!command) return;
    char* args[4] = {0,0,0,0};
    uint8_t count = 0;
    while (count < 4 && (args[count] = strtok_r(0, " ", &context))) ++count;
    if (!strcmp(command, "HELLO") && count == 1 && !strcmp(args[0], "2")) {
        Serial.print(F("CAPS 2 ")); Serial.print(MAX_KEYS);
        Serial.print(' '); Serial.print(BridgeState::WATCHDOG_MS); Serial.println(F(" 2.0.0"));
    } else if (!strcmp(command, "PANIC") && !count) {
        state.panic(); sendState(); Serial.println(F("OK PANIC"));
    } else if (!strcmp(command, "BEGIN") && count == 1 && validSession(args[0])) {
        state.begin(args[0], now); sendState();
        Serial.print(F("OK BEGIN ")); Serial.println(args[0]);
    } else if (!strcmp(command, "STATE") && count == 3 && validSession(args[0])) {
        uint32_t seq, mask;
        if (!number(args[1], 0xFFFFFFFFUL, seq) || !number(args[2], 511, mask)) { error(F("ARGUMENT")); return; }
        const BridgeState::Result result = state.setMusic(args[0], seq, mask, now);
        if (result == BridgeState::OK) sendState(); // No per-note ACK/round trip.
        else reportError(result);
    } else if (!strcmp(command, "PING") && count == 1 && validSession(args[0])) {
        const BridgeState::Result result = state.heartbeat(args[0], now);
        if (result != BridgeState::OK) { reportError(result); return; }
        Serial.print(F("OK PING ")); Serial.print(args[0]); Serial.print(' '); Serial.println(state.sequence());
    } else if (!strcmp(command, "STOP") && count == 1 && validSession(args[0])) {
        const BridgeState::Result result = state.stop(args[0]);
        if (result != BridgeState::OK) { reportError(result); return; }
        sendState(); Serial.print(F("OK STOP ")); Serial.println(args[0]);
    } else if (!count) legacy(command, now);
    else error(F("COMMAND"));
}
void setup() {
    Serial.begin(9600); // Native USB CDC, not a 9600-baud UART transport.
    Mouse.begin();
}
void loop() {
    if (state.tick(millis())) sendState();
    // Continuous incoming bytes must not starve timeouts/releases.
    for (uint8_t budget = 0; budget < 64 && Serial.available(); ++budget) {
        const char c = Serial.read();
        if (c == '\n' || c == '\r') {
            if (inputOverflow) error(F("FRAME_TOO_LONG"));
            else if (inputLength) { input[inputLength] = 0; execute(input); }
            inputLength = 0; inputOverflow = false;
        } else if (!inputOverflow) {
            if (inputLength < sizeof(input)-1 && c >= 32 && c < 127) input[inputLength++] = c;
            else inputOverflow = true;
        }
    }
}
