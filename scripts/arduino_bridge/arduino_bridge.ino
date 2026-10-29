#include <Keyboard.h>
#include <Mouse.h>

String cmdBuffer = "";

// ─── 按键码结构 ───────────────────────────────
struct KeyCode {
    char ascii;
    uint8_t special;
};

// ─── 按键名 → 键码 ─────────────────────────────
KeyCode keyToCode(String cmd) {
    if (cmd.length() == 1) {
        char k = cmd[0];
        if (k >= '0' && k <= '9')
            return {k, 0};
        if (k >= 'A' && k <= 'Z')
            return {(char)(k + ('a' - 'A')), 0};  // 小写字母 = 原始按键，不带 Shift
        if (k >= 'a' && k <= 'z')
            return {k, 0};
        return {0, 0};
    }

    cmd.toUpperCase();
    if (cmd == "ESC")       return {0, KEY_ESC};
    if (cmd == "TAB")       return {0, KEY_TAB};
    if (cmd == "SPACE")     return {' ', 0};
    if (cmd == "ENTER")     return {0, KEY_RETURN};
    if (cmd == "LCTRL")     return {0, KEY_LEFT_CTRL};
    if (cmd == "RCTRL")     return {0, KEY_RIGHT_CTRL};
    if (cmd == "LSHIFT")    return {0, KEY_LEFT_SHIFT};
    if (cmd == "RSHIFT")    return {0, KEY_RIGHT_SHIFT};
    if (cmd == "LEFT")      return {0, KEY_LEFT_ARROW};
    if (cmd == "RIGHT")     return {0, KEY_RIGHT_ARROW};
    if (cmd == "UP")        return {0, KEY_UP_ARROW};
    if (cmd == "DOWN")      return {0, KEY_DOWN_ARROW};
    if (cmd == "F1")        return {0, KEY_F1};
    if (cmd == "F2")        return {0, KEY_F2};
    if (cmd == "F3")        return {0, KEY_F3};
    if (cmd == "F4")        return {0, KEY_F4};
    if (cmd == "F5")        return {0, KEY_F5};
    if (cmd == "F6")        return {0, KEY_F6};
    if (cmd == "F7")        return {0, KEY_F7};
    if (cmd == "F8")        return {0, KEY_F8};
    if (cmd == "F9")        return {0, KEY_F9};
    if (cmd == "F10")       return {0, KEY_F10};
    if (cmd == "F11")       return {0, KEY_F11};
    if (cmd == "F12")       return {0, KEY_F12};

    return {0, 0};
}

// ─── 执行命令 ──────────────────────────────────
void execute(String raw) {
    String cmd = raw;
    int duration = 0;
    int colon = raw.indexOf(':');
    if (colon > 0) {
        cmd = raw.substring(0, colon);
        duration = raw.substring(colon + 1).toInt();
    }

    KeyCode kc = keyToCode(cmd);
    if (kc.ascii != 0 || kc.special != 0) {
        if (duration > 0) {
            if (kc.ascii) Keyboard.press(kc.ascii);
            else Keyboard.press(kc.special);
            delay(duration);
            if (kc.ascii) Keyboard.release(kc.ascii);
            else Keyboard.release(kc.special);
        } else {
            if (kc.ascii) Keyboard.write(kc.ascii);
            else Keyboard.write(kc.special);
        }
        return;
    }

    cmd.toUpperCase();
    if (cmd == "MOUSE_LEFT" || cmd == "MOUSE_RIGHT") {
        uint8_t btn = (cmd == "MOUSE_LEFT") ? MOUSE_LEFT : MOUSE_RIGHT;
        if (duration > 0) {
            Mouse.press(btn);
            delay(duration);
            Mouse.release(btn);
        } else {
            Mouse.click(btn);
        }
    }
}

// ─── 入口 ──────────────────────────────────────
void setup() {
    Serial.begin(9600);
    Keyboard.begin();
    Mouse.begin();
}

void loop() {
    while (Serial.available()) {
        char c = Serial.read();
        if (c == '\n' || c == '\r') {
            if (cmdBuffer.length() > 0) {
                execute(cmdBuffer);
                cmdBuffer = "";
            }
        } else {
            cmdBuffer += c;
        }
    }
}
