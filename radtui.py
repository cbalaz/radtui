import curses
import re
import subprocess

FILE_PATH = "/etc/raddb/users"
START_MARKER = "## BEGIN CURSES ##"
END_MARKER = "## END CURSES ##"

def load_block():
    with open(FILE_PATH) as f:
        lines = [line.rstrip("\n") for line in f]
    try:
        start = lines.index(START_MARKER)
        end = lines.index(END_MARKER)
    except ValueError:
        raise Exception("Markers not found in file")
    return lines, start, end, lines[start+1:end]

def parse_entries(block):
    entries = []
    i = 0
    while i < len(block):
        comment = device = ""
        if block[i].startswith("#"):
            comment = block[i]
            device = comment.lstrip("# ").strip()
            i += 1
        if i + 3 < len(block):
            mac_line, tt_line, tm_line, vlan_line = block[i:i+4]
            mac_match = re.match(r'^([0-9a-f:]{17})\s+Cleartext-Password := "([0-9a-f:]{17})"', mac_line, re.I)
            vlan_match = re.search(r'Tunnel-Private-Group-Id\s*=\s*(\d+)', vlan_line)
            if mac_match and vlan_match:
                entries.append({
                    "comment": comment,
                    "device_name": device,
                    "mac": mac_match.group(1),
                    "vlan": vlan_match.group(1),
                    "index": i,
                    "lines": [comment, mac_line, tt_line, tm_line, vlan_line] if comment else [mac_line, tt_line, tm_line, vlan_line]
                })
                i += 4
                continue
        i += 1
    return entries

def save_changes(all_lines, start, end, entries):
    new_block = []
    for e in entries:
        if e["device_name"]:
            new_block.append(f"# {e['device_name']}")
        new_block += [
            f'{e["mac"]}       Cleartext-Password := "{e["mac"]}"',
            "                        Tunnel-Type = VLAN,",
            "                        Tunnel-Medium-Type = 6,",
            f"                        Tunnel-Private-Group-Id = {e['vlan']}"
        ]
    with open(FILE_PATH, "w") as f:
        f.write("\n".join(all_lines[:start+1] + new_block + all_lines[end:]) + "\n")

def popup_edit(stdscr, entry):
    max_y, max_x = stdscr.getmaxyx()
    w, h = 56, 11
    start_x = (max_x - w) // 2
    start_y = (max_y - h) // 2

    win = curses.newwin(h, w, start_y, start_x)
    win.keypad(True)

    fields = ["mac", "vlan", "device_name"]
    labels = ["MAC Address (xx:xx:xx:xx:xx:xx):", "VLAN ID (number):", "Device Name:"]
    values = [list(entry.get(field, "")) for field in fields]
    current_field = 0
    cursor_pos = len(values[current_field])
    error_msg = ""

    curses.curs_set(0)

    def draw():
        win.clear()
        win.border()

        # Title bar
        win.attron(curses.color_pair(6) | curses.A_BOLD)
        win.addstr(0, (w - 13)//2, " Edit Entry ")
        win.attroff(curses.color_pair(6) | curses.A_BOLD)

        # Draw fields with labels and input areas
        for i, label in enumerate(labels):
            y = 2 + i*2
            val_str = "".join(values[i])
            win.attron(curses.A_BOLD)
            win.addstr(y, 2, label)
            win.attroff(curses.A_BOLD)
            # Draw input text field padded
            win.addstr(y, len(label) + 3, val_str.ljust(w - len(label) - 6), curses.color_pair(7))
            # Highlight cursor position
            if i == current_field:
                pos = len(label) + 3 + cursor_pos
                if pos >= w - 1:
                    pos = w - 2
                ch = val_str[cursor_pos] if 0 <= cursor_pos < len(val_str) else " "
                win.addch(y, pos, ch, curses.color_pair(8))

        # Show error or instructions line
        if error_msg:
            win.attron(curses.color_pair(4) | curses.A_BOLD)
            win.addstr(h - 3, 2, error_msg.center(w - 4))
            win.attroff(curses.color_pair(4) | curses.A_BOLD)
        else:
            win.attron(curses.color_pair(7))
            win.addstr(h - 3, 2, "Enter=Save  Esc=Cancel".center(w - 4))
            win.attroff(curses.color_pair(7))

        win.refresh()

    while True:
        draw()
        key = win.getch()

        if key in (curses.KEY_ENTER, 10, 13):
            mac_str = "".join(values[0]).lower()
            vlan_str = "".join(values[1])
            if not re.fullmatch(r"([0-9a-f]{2}:){5}[0-9a-f]{2}", mac_str):
                error_msg = "Invalid MAC address format!"
                curses.beep()
                continue
            if not vlan_str.isdigit():
                error_msg = "VLAN must be a number!"
                curses.beep()
                continue
            entry["mac"] = mac_str
            entry["vlan"] = vlan_str
            entry["device_name"] = "".join(values[2]).strip()
            return True

        elif key == 27:
            return False

        elif key in (curses.KEY_DOWN, 9):
            current_field = (current_field + 1) % len(fields)
            cursor_pos = len(values[current_field])
            error_msg = ""

        elif key == curses.KEY_UP:
            current_field = (current_field - 1) % len(fields)
            cursor_pos = len(values[current_field])
            error_msg = ""

        elif key == curses.KEY_LEFT and cursor_pos > 0:
            cursor_pos -= 1

        elif key == curses.KEY_RIGHT and cursor_pos < len(values[current_field]):
            cursor_pos += 1

        elif key in (curses.KEY_BACKSPACE, 127, 8) and cursor_pos > 0:
            values[current_field].pop(cursor_pos-1)
            cursor_pos -= 1

        elif key == curses.KEY_DC and cursor_pos < len(values[current_field]):
            values[current_field].pop(cursor_pos)

        elif 32 <= key <= 126:
            values[current_field].insert(cursor_pos, chr(key))
            cursor_pos += 1

        if cursor_pos < 0:
            cursor_pos = 0
        if cursor_pos > len(values[current_field]):
            cursor_pos = len(values[current_field])
        error_msg = ""

def show_message(stdscr, message):
    max_y, max_x = stdscr.getmaxyx()
    lines = message.split("\n")
    w = max(len(line) for line in lines) + 6
    h = len(lines) + 5
    start_x = (max_x - w) // 2
    start_y = (max_y - h) // 2

    win = curses.newwin(h, w, start_y, start_x)
    win.border()

    win.attron(curses.color_pair(6) | curses.A_BOLD)
    win.addstr(0, (w - 7)//2, " Message ")
    win.attroff(curses.color_pair(6) | curses.A_BOLD)

    for idx, line in enumerate(lines):
        win.addstr(2 + idx, 3, line.center(w - 6))
    win.attron(curses.color_pair(7))
    win.addstr(h - 2, w - 16, "<Press any key>")
    win.attroff(curses.color_pair(7))

    win.refresh()
    win.getch()

def popup_confirm(stdscr, message):
    max_y, max_x = stdscr.getmaxyx()
    w = max(len(message) + 10, 38)
    h = 7
    start_x = (max_x - w) // 2
    start_y = (max_y - h) // 2

    win = curses.newwin(h, w, start_y, start_x)
    win.keypad(True)
    win.border()

    win.attron(curses.color_pair(5) | curses.A_BOLD)
    win.addstr(0, (w - 9)//2, " Confirm ")
    win.attroff(curses.color_pair(5) | curses.A_BOLD)

    win.addstr(2, 4, message.center(w - 8))
    win.addstr(4, 4, "Y=Yes / N=No".center(w - 8))
    win.refresh()

    while True:
        key = win.getch()
        if key in (ord('y'), ord('Y')):
            return True
        elif key in (ord('n'), ord('N'), 27):
            return False

def curses_main(stdscr):
    curses.curs_set(0)
    stdscr.keypad(True)
    curses.start_color()

    # Color pairs:
    # 1: Selected line - black on cyan
    # 3: Header - yellow on black (bold + underline)
    # 4: Error text - red on black bold
    # 5: Confirm popup title - white on magenta bold
    # 6: Popup title bars - black on white bold
    # 7: Input text background - black on white
    # 8: Cursor position highlight in input - white on blue bold
    curses.init_pair(1, curses.COLOR_BLACK, curses.COLOR_CYAN)
    curses.init_pair(3, curses.COLOR_YELLOW, curses.COLOR_BLACK)
    curses.init_pair(4, curses.COLOR_RED, curses.COLOR_BLACK)
    curses.init_pair(5, curses.COLOR_WHITE, curses.COLOR_MAGENTA)
    curses.init_pair(6, curses.COLOR_BLACK, curses.COLOR_WHITE)
    curses.init_pair(7, curses.COLOR_BLACK, curses.COLOR_WHITE)
    curses.init_pair(8, curses.COLOR_WHITE, curses.COLOR_BLUE)

    all_lines, start, end, block = load_block()
    entries = parse_entries(block)
    selected = 0
    scroll_pos = 0

    def draw():
        stdscr.clear()
        max_y, max_x = stdscr.getmaxyx()

        # Title bar top line
        title = "RADIUS Users Editor"
        stdscr.attron(curses.color_pair(6) | curses.A_BOLD)
        stdscr.addstr(0, 0, " " * max_x)
        stdscr.addstr(0, (max_x - len(title)) // 2, title)
        stdscr.attroff(curses.color_pair(6) | curses.A_BOLD)

        # Draw a border box around the list
        box_top = 1
        box_left = 0
        box_height = max_y - 4
        box_width = max_x

        stdscr.attron(curses.color_pair(3) | curses.A_BOLD | curses.A_UNDERLINE)
        stdscr.addstr(box_top, 2, f"{'MAC Address':20} | {'VLAN':6} | Device Name")
        stdscr.attroff(curses.color_pair(3) | curses.A_BOLD | curses.A_UNDERLINE)

        # Draw horizontal line under header
        stdscr.hline(box_top + 1, 1, curses.ACS_HLINE, box_width - 2)

        # Draw vertical borders
        stdscr.vline(box_top + 2, 0, curses.ACS_VLINE, box_height - 2)
        stdscr.vline(box_top + 2, box_width - 1, curses.ACS_VLINE, box_height - 2)
        # Draw corners
        stdscr.addch(box_top + 1, 0, curses.ACS_ULCORNER)
        stdscr.addch(box_top + box_height, 0, curses.ACS_LLCORNER)
        stdscr.addch(box_top + 1, box_width - 1, curses.ACS_URCORNER)
        stdscr.addch(box_top + box_height, box_width - 1, curses.ACS_LRCORNER)
        stdscr.hline(box_top + box_height, 1, curses.ACS_HLINE, box_width - 2)

        visible_height = box_height - 2
        nonlocal scroll_pos
        if selected < scroll_pos:
            scroll_pos = selected
        elif selected >= scroll_pos + visible_height:
            scroll_pos = selected - visible_height + 1

        for idx in range(scroll_pos, min(scroll_pos + visible_height, len(entries))):
            e = entries[idx]
            y = box_top + 2 + idx - scroll_pos
            line = f"{e['mac']:20} | {e['vlan']:6} | {e['device_name']}"
            if idx == selected:
                stdscr.attron(curses.color_pair(1))
                stdscr.addstr(y, 2, line[:box_width-4])
                stdscr.attroff(curses.color_pair(1))
            else:
                stdscr.addstr(y, 2, line[:box_width-4])

        # Footer/status bar
        status = ("Up/Down: Navigate | Enter: Edit | a: Add | d: Delete | "
                  "r: Restart radiusd | F2: Save | F10: Quit | "
                  f"Total entries: {len(entries)}")
        stdscr.attron(curses.color_pair(6) | curses.A_BOLD)
        stdscr.addstr(max_y - 2, 0, " " * max_x)
        stdscr.addstr(max_y - 2, 2, status[:max_x - 4])
        stdscr.attroff(curses.color_pair(6) | curses.A_BOLD)

        stdscr.refresh()

    while True:
        draw()
        key = stdscr.getch()

        if key == curses.KEY_UP and selected > 0:
            selected -= 1

        elif key == curses.KEY_DOWN and selected < len(entries) - 1:
            selected += 1

        elif key in (10, 13):  # Enter key to edit
            if entries and popup_edit(stdscr, entries[selected]):
                entry = entries[selected]
                new_lines = []
                if entry["device_name"]:
                    new_lines.append(f"# {entry['device_name']}")
                new_lines += [
                    f'{entry["mac"]}       Cleartext-Password := "{entry["mac"]}"',
                    "                        Tunnel-Type = VLAN,",
                    "                        Tunnel-Medium-Type = 6,",
                    f"                        Tunnel-Private-Group-Id = {entry['vlan']}"
                ]
                entries[selected]["lines"] = new_lines

        elif key in (ord('a'), ord('A')):
            new_entry = {"mac": "", "vlan": "", "device_name": "", "lines": []}
            if popup_edit(stdscr, new_entry):
                entries.append(new_entry)
                selected = len(entries) - 1

        elif key in (ord('d'), ord('D')):
            if entries:
                confirm = popup_confirm(stdscr, "Delete selected entry? This cannot be undone!")
                if confirm:
                    entries.pop(selected)
                    if selected >= len(entries):
                        selected = max(0, len(entries) - 1)

        elif key in (ord('r'), ord('R')):
            confirm = popup_confirm(stdscr, "Restart radiusd service now?")
            if confirm:
                try:
                    subprocess.run(["sudo", "systemctl", "restart", "radiusd"], check=True)
                    show_message(stdscr, "radiusd service restarted successfully!")
                except Exception as e:
                    show_message(stdscr, f"Failed to restart radiusd:\n{e}")

        elif key == curses.KEY_F2:
            save_changes(all_lines, start, end, entries)
            show_message(stdscr, "Changes saved successfully.")

        elif key == curses.KEY_F10:
            break

def main():
    curses.wrapper(curses_main)

if __name__ == "__main__":
    main()

