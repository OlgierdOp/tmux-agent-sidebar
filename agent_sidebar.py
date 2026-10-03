#!/usr/bin/env python3
"""tmux agent sidebar: a list of the Claude Code agents running in tmux panes.

Every window has its own sidebar pane (no panes move around, so nothing flickers).
Shared state (selection, filter, home session) lives in global tmux options.

Usage:
  agent_sidebar.py            # TUI of one sidebar pane
  agent_sidebar.py toggle     # turn the sidebars on/off in all windows
  agent_sidebar.py ensure W   # tmux hook: add a sidebar to window W if it has none
  agent_sidebar.py next       # jump to the agent that is waiting for you
"""

import curses
import json
import os
import re
import subprocess
import sys
import time

# ---------------------------------------------------------------- config

LANG = "en"
SIDEBAR_WIDTH = int(os.environ.get("AGENT_SIDEBAR_WIDTH", "42"))
SEL_BG = 60                 # default selection background (xterm-256), overridden by @agent_sidebar_bg
# backgrounds cycled by the `c` key (live preview in all sidebars)
BG_CHOICES = [60, 61, 24, 25, 23, 29, 22, 53, 54, 89, 52, 94, 17, 18, 235, 236, 237, 238]

STRINGS = {
    "en": {
        "title": "AGENTS",
        "no_agents": "No Claude Code agents",
        "no_git": "(not a git repo)",
        "help": "⏎ show  i enter  s session  c color",
        "rename": "agent name:",
        "none_waiting": "No agent is waiting",
        "outside_tmux": "agent_sidebar: run inside tmux",
    },
}
T = STRINGS[LANG]

POLL_SEC = 0.25             # visibility / key polling
REFRESH_SEC = 1.0           # data refresh while the pane is visible
HIDDEN_REFRESH_SEC = 5.0    # ... and while it is hidden
GIT_TTL_SEC = 3.0
SEP = "\t"

# status -> (symbol, curses color, priority for `next`)
STATUS = {
    "waiting": ("●", "red", 0),      # needs your approval / answer
    "done": ("●", "green", 1),       # finished, not looked at yet
    "working": ("◐", "yellow", 2),
    "idle": ("○", "gray", 3),
    "unknown": ("?", "gray", 4),     # no hook data
}
SPINNER = "◐◓◑◒"


# ---------------------------------------------------------------- tmux / proc

def tmux(*args, check=False):
    r = subprocess.run(["tmux", *args], capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(r.stderr.strip())
    return r.stdout


PANE_FIELDS = [
    "pane_id", "pane_pid", "session_name", "window_id", "window_index", "window_name",
    "pane_index", "pane_title", "pane_current_path", "pane_active",
    "window_active", "session_attached",
    "@agent_status", "@agent_ts", "@agent_name", "@agent_sidebar",
    "@agent_transcript",
]


def list_panes():
    fmt = SEP.join("#{%s}" % f for f in PANE_FIELDS)
    panes = []
    for line in tmux("list-panes", "-a", "-F", fmt).splitlines():
        parts = line.split(SEP)
        if len(parts) == len(PANE_FIELDS):
            panes.append(dict(zip(PANE_FIELDS, parts)))
    return panes


def process_children():
    """Map ppid -> [(pid, comm, argv)] built from /proc."""
    children = {}
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        try:
            with open(f"/proc/{entry}/stat") as f:
                stat = f.read()
            with open(f"/proc/{entry}/cmdline", "rb") as f:
                argv = f.read().split(b"\0")
        except OSError:
            continue
        # comm is in parentheses and may contain spaces
        comm = stat[stat.find("(") + 1:stat.rfind(")")]
        ppid = int(stat[stat.rfind(")") + 2:].split()[1])
        args = [a.decode(errors="replace") for a in argv if a]
        children.setdefault(ppid, []).append((int(entry), comm, args))
    return children


def is_claude(comm, args):
    if comm == "claude":
        return True
    return any(os.path.basename(a) == "claude" or "claude-code" in a for a in args[:2])


def claude_pid_in(pane_pid, children, depth=4):
    try:
        with open(f"/proc/{pane_pid}/comm") as f:
            comm = f.read().strip()
        with open(f"/proc/{pane_pid}/cmdline", "rb") as f:
            args = [a.decode(errors="replace") for a in f.read().split(b"\0") if a]
        if is_claude(comm, args):
            return pane_pid
    except OSError:
        pass
    stack = [(pane_pid, 0)]
    while stack:
        pid, d = stack.pop()
        for child, comm, args in children.get(pid, []):
            if is_claude(comm, args):
                return child
            if d < depth:
                stack.append((child, d + 1))
    return None


def proc_cwd(pid, fallback):
    try:
        return os.readlink(f"/proc/{pid}/cwd")
    except OSError:
        return fallback


# ---------------------------------------------------------------- git

_git_cache = {}


def _git(path, *args):
    try:
        r = subprocess.run(["git", "-C", path, *args], capture_output=True,
                           text=True, timeout=2)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def git_info(path):
    """(toplevel, branch, is_linked_worktree) or None, briefly cached."""
    now = time.monotonic()
    hit = _git_cache.get(path)
    if hit and now - hit[0] < GIT_TTL_SEC:
        return hit[1]
    info = None
    out = _git(path, "rev-parse", "--show-toplevel", "--absolute-git-dir",
               "--path-format=absolute", "--git-common-dir")
    if out:
        lines = out.splitlines()
        if len(lines) == 3:
            top, git_dir, common = lines
            branch = (_git(path, "symbolic-ref", "--short", "-q", "HEAD")
                      or _git(path, "rev-parse", "--short", "HEAD") or "?")
            info = (top, branch, os.path.realpath(git_dir) != os.path.realpath(common))
    _git_cache[path] = (now, info)
    return info


def short_path(p, width=None):
    home = os.path.expanduser("~")
    p = "~" + p[len(home):] if p.startswith(home) else p
    if width and len(p) > width:
        p = "…" + p[-(width - 1):]  # the end of the path matters most
    return p


# ---------------------------------------------------------------- tokens

_token_cache = {}


def guess_transcript(cwd):
    """Fallback without hook data: newest project transcript for this cwd."""
    d = os.path.expanduser("~/.claude/projects/" + re.sub(r"[^A-Za-z0-9]", "-", cwd))
    try:
        files = [os.path.join(d, f) for f in os.listdir(d) if f.endswith(".jsonl")]
    except OSError:
        return None
    return max(files, key=os.path.getmtime) if files else None


def context_tokens(path):
    """Context size from the last assistant reply in the transcript."""
    if not path:
        return None
    try:
        st = os.stat(path)
    except OSError:
        return None
    key = (st.st_mtime_ns, st.st_size)
    hit = _token_cache.get(path)
    if hit and hit[0] == key:
        return hit[1]
    tokens = None
    try:
        with open(path, "rb") as f:
            f.seek(max(0, st.st_size - 512 * 1024))
            lines = f.read().splitlines()
        for line in reversed(lines):
            if b'"usage"' not in line:
                continue
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if entry.get("isSidechain") or entry.get("type") != "assistant":
                continue
            u = entry.get("message", {}).get("usage") or {}
            tokens = sum(u.get(k) or 0 for k in (
                "input_tokens", "cache_creation_input_tokens",
                "cache_read_input_tokens", "output_tokens"))
            break
    except OSError:
        pass
    _token_cache[path] = (key, tokens)
    return tokens


def fmt_tokens(n):
    if n is None:
        return ""
    if n < 1000:
        return str(n)
    if n < 1_000_000:
        return f"{n // 1000}k"
    return f"{n / 1_000_000:.1f}M"


# ---------------------------------------------------------------- model

def current_session(pane=None):
    args = ["-t", pane] if pane else []
    return tmux("display-message", "-p", *args, "#{session_name}").strip()


def collect_agents(home_session=None):
    children = process_children()
    agents = []
    for p in list_panes():
        if p["@agent_sidebar"]:
            continue
        pid = claude_pid_in(int(p["pane_pid"]), children)
        if pid is None and not p["@agent_status"]:
            continue
        cwd = proc_cwd(pid, p["pane_current_path"]) if pid else p["pane_current_path"]
        status = p["@agent_status"] or "unknown"
        if pid is None:
            status = "idle" if status != "unknown" else status
        try:
            ts = int(p["@agent_ts"])
        except ValueError:
            ts = None
        agents.append({
            "pane": p["pane_id"],
            "session": p["session_name"],
            "window_id": p["window_id"],
            "order": (int(p["window_index"]), int(p["pane_index"])),
            "window": p["window_name"],
            "name": p["@agent_name"],
            "cwd": cwd,
            "git": git_info(cwd),
            "tokens": context_tokens(p["@agent_transcript"] or guess_transcript(cwd)),
            "status": status if status in STATUS else "unknown",
            "ts": ts,
        })
    # home session first, then the others alphabetically
    agents.sort(key=lambda a: (a["session"] != home_session, a["session"], a["order"]))
    return agents


# ---------------------------------------------------------------- sidebar panes

def gopt(name):
    return tmux("show-option", "-gqv", name).strip()


def sidebar_in(window):
    for line in tmux("list-panes", "-t", window, "-F",
                     "#{pane_id}\t#{@agent_sidebar}").splitlines():
        pane, flag = line.split("\t")
        if flag == "1":
            return pane
    return None


def ensure(window):
    """Add a sidebar to the window (keeps the active pane). Returns its id."""
    if not window or gopt("@agent_sidebar_on") != "1":
        return None
    sb = sidebar_in(window)
    if sb:
        return sb
    sb = tmux("split-window", "-d", "-hbf", "-l", str(SIDEBAR_WIDTH), "-t", window,
              "-P", "-F", "#{pane_id}",
              f"{sys.executable} {os.path.abspath(__file__)}").strip()
    if sb:
        tmux("set-option", "-p", "-t", sb, "@agent_sidebar", "1")
    return sb or None


def jump(agent, focus=True):
    """Show the agent's window. focus=False: the cursor stays in the sidebar."""
    pane = agent["pane"]
    window = tmux("display-message", "-p", "-t", pane, "#{window_id}").strip()
    # add the sidebar before the window becomes visible
    sb = ensure(window)
    if sb and sb != os.environ.get("TMUX_PANE"):
        # wait (max ~150 ms) until the target window's sidebar draws the new selection
        for _ in range(15):
            if tmux("display-message", "-p", "-t", sb, "#{@agent_sidebar_drawn}").strip() == pane:
                break
            time.sleep(0.01)
    tmux("select-window", "-t", window)
    tmux("select-pane", "-t", pane)
    tmux("switch-client", "-t", pane)
    if sb and not focus:
        # the agent stays the "last" pane, so Ctrl+l / prefix ; lands on it
        tmux("select-pane", "-t", sb)
    tmux("set-option", "-g", "@agent_sidebar_sel", pane)
    if agent["status"] == "done":
        # seen -> no longer highlighted
        tmux("set-option", "-p", "-t", pane, "@agent_status", "idle")


# ---------------------------------------------------------------- TUI

class UI:
    LINES_PER_AGENT = 3  # name, branch, worktree (+ separator)

    def __init__(self, scr):
        self.scr = scr
        self.me = os.environ.get("TMUX_PANE", "")
        self.sel = 0
        self.scroll = 0
        self.agents = []
        self.rows = []      # (y_start, y_end, index) for mouse clicks
        self.own = None     # session this pane is in (◆)
        self.home = None    # home session: always at the top of the list
        self.only_home = False
        self.shared_sel = ""
        self.visible = True
        self.last_refresh = 0.0
        self.drawn_sel = None
        self.active_pane = None  # active pane of this window
        curses.curs_set(0)
        curses.use_default_colors()
        curses.mousemask(curses.BUTTON1_CLICKED | curses.BUTTON1_PRESSED)
        self.scr.timeout(int(POLL_SEC * 1000))
        palette = {"text": -1, "red": curses.COLOR_RED, "green": curses.COLOR_GREEN,
                   "yellow": curses.COLOR_YELLOW, "blue": curses.COLOR_BLUE,
                   "magenta": curses.COLOR_MAGENTA, "cyan": curses.COLOR_CYAN,
                   "gray": 8 if curses.COLORS > 8 else curses.COLOR_WHITE}
        self.palette = palette
        self.colors, self.sel_colors = {}, {}
        for i, (name, c) in enumerate(palette.items()):
            curses.init_pair(2 * i + 1, c, -1)
            self.colors[name] = curses.color_pair(2 * i + 1)
            self.sel_colors[name] = curses.color_pair(2 * i + 2)
        self.bg = None
        self.bg_shown_until = 0.0
        self.set_bg(SEL_BG)

    def set_bg(self, bg):
        rich = curses.COLORS >= 256
        if bg == self.bg:
            return
        self.bg = bg
        for i, (name, c) in enumerate(self.palette.items()):
            # dark gray text disappears on a colored selection background
            curses.init_pair(2 * i + 2, 252 if name == "gray" and rich else c,
                             bg if rich else curses.COLOR_BLACK)

    # --- shared state in tmux options

    def poll_state(self):
        """Cheap check of visibility and shared state. False = exit."""
        out = tmux("display-message", "-p", "-t", self.me, SEP.join([
            "#{@agent_sidebar_on}", "#{@agent_sidebar_sel}", "#{@agent_sidebar_only}",
            "#{@agent_sidebar_home}", "#{session_name}", "#{window_panes}",
            "#{&&:#{window_active},#{session_attached}}", "#{pane_width}",
            "#{@agent_sidebar_bg}", "#{P:#{?pane_active,#{pane_id},}}", "#{window_id}"]))
        parts = out.rstrip("\n").split(SEP)
        if len(parts) != 11 or parts[0] != "1":
            return False
        on, sel, only, home, own, panes, visible, width, bg, active, window = parts
        if bg.isdigit() and int(bg) != self.bg:
            self.set_bg(int(bg))
            self.bg_shown_until = time.monotonic() + 3
        if visible == "1" and width != str(SIDEBAR_WIDTH):
            # tmux scales panes proportionally when the window is resized
            tmux("resize-pane", "-t", self.me, "-x", str(SIDEBAR_WIDTH))
        if panes == "1":  # alone in the window (the agent exited)
            return False
        # cheap changes: redraw from the data we already have
        redraw = (sel != self.shared_sel or visible == "1" and active != self.active_pane)
        # changes that need fresh data
        became_visible = visible == "1" and not self.visible
        changed = ((only == "1") != self.only_home or home != self.home or own != self.own
                   or became_visible)
        focus_moved = visible == "1" and active != self.active_pane
        self.shared_sel, self.only_home = sel, only == "1"
        self.home, self.own, self.visible = home or own, own, visible == "1"
        self.active_pane = active
        if became_visible or focus_moved:
            self.follow(window, active)
        if changed:
            return "refresh"
        return "redraw" if redraw else True

    def follow(self, window, active):
        """The selection follows you when you move with tmux keys or scripts.

        Focus in an agent pane -> select that agent. Otherwise (focus in the
        sidebar) select an agent of this window, unless one is selected already.
        """
        mine = [a["pane"] for a in self.agents if a["window_id"] == window]
        if active in mine:
            target = active
        elif mine and self.shared_sel not in mine:
            target = mine[0]
        else:
            return
        if target != self.shared_sel:
            self.shared_sel = target
            tmux("set-option", "-g", "@agent_sidebar_sel", target)

    def select(self, i):
        if 0 <= i < len(self.agents):
            self.sel = i
            self.shared_sel = self.agents[i]["pane"]
            # store it and "poke" (F12) the other sidebars right away, so after a
            # window switch they never show the old selection for a moment
            cmd = ["set-option", "-g", "@agent_sidebar_sel", self.shared_sel]
            for line in tmux("list-panes", "-a", "-F",
                             "#{pane_id}\t#{@agent_sidebar}").splitlines():
                pane, flag = line.split("\t")
                if flag == "1" and pane != self.me:
                    cmd += [";", "send-keys", "-t", pane, "F12"]
            tmux(*cmd)

    def sync_sel(self):
        self.sel = next((i for i, a in enumerate(self.agents) if a["pane"] == self.shared_sel),
                        self.sel)

    def refresh_data(self):
        agents = collect_agents(self.home)
        if self.only_home:
            agents = [a for a in agents if a["session"] == self.home]
        self.agents = agents
        self.sel = next((i for i, a in enumerate(agents) if a["pane"] == self.shared_sel),
                        max(0, min(self.sel, len(agents) - 1)))
        self.last_refresh = time.monotonic()

    # --- drawing

    def put(self, y, x, text, attr=0):
        h, w = self.scr.getmaxyx()
        if 0 <= y < h and x < w:
            try:
                self.scr.addnstr(y, x, text, max(0, w - x - 1), attr)
            except curses.error:
                pass

    def counts_label(self, agents):
        counts = {}
        for a in agents:
            counts[a["status"]] = counts.get(a["status"], 0) + 1
        return [(f"{STATUS[st][0]}{counts[st]}", STATUS[st][1])
                for st in ("waiting", "done", "working") if counts.get(st)]

    def layout(self):
        """Virtual rows: [(y, 'header', session) | (y, 'agent', index)]."""
        items, y, prev = [], 0, None
        for i, a in enumerate(self.agents):
            if a["session"] != prev:
                if prev is not None:
                    y += 1
                items.append((y, "header", a["session"]))
                y += 1
                prev = a["session"]
            items.append((y, "agent", i))
            y += self.LINES_PER_AGENT + 1
        return items

    def draw(self):
        self.scr.erase()
        h, w = self.scr.getmaxyx()
        self.put(0, 1, T["title"], curses.A_BOLD)
        x = len(T["title"]) + 2
        for label, col in self.counts_label(self.agents):
            self.put(0, x, label, self.colors[col] | curses.A_BOLD)
            x += len(label) + 1
        if time.monotonic() < self.bg_shown_until:
            label = f"bg {self.bg}"
            self.put(0, w - len(label) - 2, label, self.sel_colors["text"] | curses.A_BOLD)
        elif self.only_home and self.home:
            self.put(0, max(x + 1, w - len(self.home) - 4), f"[{self.home}]", self.colors["cyan"])
        self.put(1, 0, "─" * (w - 1), self.colors["gray"])

        self.rows = []
        top, avail = 2, max(1, h - 3)
        if not self.agents:
            self.put(top, 1, T["no_agents"], self.colors["gray"])
        items = self.layout()
        # scrolling: keep the selected agent (and its session header) in view
        per = self.LINES_PER_AGENT + 1
        for idx, (y, kind, ref) in enumerate(items):
            if kind == "agent" and ref == self.sel:
                y0 = items[idx - 1][0] if items[idx - 1][1] == "header" else y
                if y0 < self.scroll:
                    self.scroll = y0
                elif y + per > self.scroll + avail:
                    self.scroll = y + per - avail
        for y, kind, ref in items:
            sy = y - self.scroll + top
            if sy < top or sy >= h - 1:
                continue
            if kind == "header":
                self.draw_header(sy, ref, w)
            else:
                self.draw_agent(sy, ref, self.agents[ref], w)
                self.rows.append((sy, sy + per - 1, ref))
        self.put(h - 1, 1, T["help"], self.colors["gray"])
        self.scr.refresh()
        sel = self.agents[self.sel]["pane"] if self.agents else ""
        if sel != self.drawn_sel:
            # jump() waits for this before it shows the window of this sidebar
            self.drawn_sel = sel
            tmux("set-option", "-p", "-t", self.me, "@agent_sidebar_drawn", sel)

    def draw_header(self, y, session, w):
        attr = self.colors["cyan"] | curses.A_BOLD
        own = " ◆" if session == self.own else ""
        head = f"━━ {session}{own} "
        self.put(y, 0, head, attr)
        x = len(head)
        for label, col in self.counts_label([a for a in self.agents if a["session"] == session]):
            self.put(y, x, label + " ", self.colors[col] | curses.A_BOLD)
            x += len(label) + 1
        self.put(y, x, "━" * max(0, w - x - 1), self.colors["cyan"])

    def draw_agent(self, y, i, a, w):
        selected = i == self.sel
        c = self.sel_colors if selected else self.colors
        if selected:
            for dy in range(self.LINES_PER_AGENT):
                self.put(y + dy, 0, " " * (w - 1), c["text"])
        sym, col, _ = STATUS[a["status"]]
        if a["status"] == "working":
            sym = SPINNER[int(time.time() * 2) % len(SPINNER)]
        self.put(y, 1, sym, c[col] | curses.A_BOLD)
        self.put(y, 2, f" {i + 1} {a['name'] or a['window']}", c["text"] | curses.A_BOLD)
        tokens = fmt_tokens(a["tokens"])
        if tokens:
            self.put(y, w - len(tokens) - 2, tokens, c["gray"])
        g = a["git"]
        if g:
            top, branch, linked = g
            self.put(y + 1, 3, "⎇ " + branch, c["magenta"])
            tag = " [wt]" if linked else ""
            path = short_path(top, w - 7 - len(tag))
            self.put(y + 2, 3, ("⊕ " if linked else "⌂ ") + path + tag, c["blue"])
        else:
            self.put(y + 1, 3, T["no_git"], c["gray"])
            self.put(y + 2, 3, "⌂ " + short_path(a["cwd"], w - 7), c["blue"])
        self.put(y + 3, 1, "┄" * (w - 3), self.colors["gray"])

    # --- actions

    def go(self, i, focus=False):
        if 0 <= i < len(self.agents):
            self.select(i)
            jump(self.agents[i], focus=focus)

    def next_waiting(self):
        n = len(self.agents)
        for off in range(1, n + 1):
            i = (self.sel + off) % n
            if self.agents[i]["status"] in ("waiting", "done"):
                self.select(i)
                return

    def rename(self):
        if not self.agents:
            return
        a = self.agents[self.sel]
        tmux("command-prompt", "-I", a["name"] or a["window"], "-p", T["rename"],
             f"set-option -p -t {a['pane']} @agent_name '%%'")

    def handle_key(self, k):
        if k in (ord("j"), curses.KEY_DOWN):
            self.select(min(self.sel + 1, len(self.agents) - 1))
        elif k in (ord("k"), curses.KEY_UP):
            self.select(max(self.sel - 1, 0))
        elif k == ord("g"):
            self.select(0)
        elif k == ord("G"):
            self.select(len(self.agents) - 1)
        elif k in (10, 13, curses.KEY_ENTER, ord("o")):
            self.go(self.sel)
        elif k == ord("i"):
            self.go(self.sel, focus=True)
        elif ord("1") <= k <= ord("9"):
            self.go(k - ord("1"))
        elif k == 9:  # tab
            self.next_waiting()
        elif k == ord("s"):
            tmux("set-option", "-g", "@agent_sidebar_only", "" if self.only_home else "1")
            self.scroll = 0
        elif k == ord("n"):
            self.rename()
        elif k == ord("c"):
            i = BG_CHOICES.index(self.bg) + 1 if self.bg in BG_CHOICES else 0
            bg = BG_CHOICES[i % len(BG_CHOICES)]
            tmux("set-option", "-g", "@agent_sidebar_bg", str(bg))
            # the other sidebars read the new color on their next poll
            self.set_bg(bg)
            self.bg_shown_until = time.monotonic() + 3
        elif k == ord("r"):
            _git_cache.clear()
        elif k == curses.KEY_MOUSE:
            try:
                _, _, my, _, _ = curses.getmouse()
            except curses.error:
                return
            for y0, y1, i in self.rows:
                if y0 <= my <= y1:
                    self.go(i)

    def update(self, state):
        """Redraw at once from the data we have, then refresh the data if needed."""
        if state in ("redraw", "refresh"):
            self.sync_sel()
            self.draw()
        age = time.monotonic() - self.last_refresh
        if state == "refresh" or age >= (REFRESH_SEC if self.visible else HIDDEN_REFRESH_SEC):
            self.refresh_data()
            self.draw()

    def run(self):
        if not self.poll_state():
            return
        self.update("refresh")
        while True:
            k = self.scr.getch()
            if k not in (-1, curses.KEY_RESIZE, curses.KEY_F12):
                self.handle_key(k)
            # F12 = a tmux hook (window switch) or another sidebar wants a redraw now
            state = self.poll_state()
            if not state:
                return
            if k not in (-1, curses.KEY_F12) and state is True:
                state = "redraw"
            self.update(state)
            if state is True and self.visible:
                self.draw()  # spinner animation


# ---------------------------------------------------------------- commands

def cmd_toggle():
    if gopt("@agent_sidebar_on") == "1":
        tmux("set-option", "-gu", "@agent_sidebar_on")
        for line in tmux("list-panes", "-a", "-F", "#{pane_id}\t#{@agent_sidebar}").splitlines():
            pane, flag = line.split("\t")
            if flag == "1":
                tmux("kill-pane", "-t", pane)
        return
    tmux("set-option", "-g", "@agent_sidebar_on", "1")
    tmux("set-option", "-g", "@agent_sidebar_home", current_session())
    here = tmux("display-message", "-p", "#{window_id}").strip()
    # all windows at once: each one is resized only this one time
    for window in tmux("list-windows", "-a", "-F", "#{window_id}").split():
        ensure(window)
    sb = sidebar_in(here)
    if sb:
        tmux("select-pane", "-t", sb)


def cmd_next():
    home = gopt("@agent_sidebar_home") or current_session()
    own = current_session()
    candidates = [a for a in collect_agents(home) if a["status"] in ("waiting", "done")]
    if not candidates:
        tmux("display-message", T["none_waiting"])
        return
    # current session first, then "waiting" before "done", longest waiting first
    candidates.sort(key=lambda a: (a["session"] != own, STATUS[a["status"]][2], a["ts"] or 0))
    jump(candidates[0])


def startup_dedupe():
    """Two hooks at once may add two sidebars to one window. The older one stays."""
    me = os.environ.get("TMUX_PANE", "")
    tmux("set-option", "-p", "-t", me, "@agent_sidebar", "1")
    window = tmux("display-message", "-p", "-t", me, "#{window_id}").strip()
    others = [p for p in tmux("list-panes", "-t", window, "-F",
                              "#{pane_id}\t#{@agent_sidebar}").splitlines()
              if p.endswith("\t1") and not p.startswith(me + "\t")]
    return not any(int(p[1:].split("\t")[0]) < int(me[1:]) for p in others)


def main():
    args = sys.argv[1:]
    if args[:1] == ["toggle"]:
        return cmd_toggle()
    if args[:1] == ["ensure"]:
        return ensure(args[1] if len(args) > 1 else "")
    if args[:1] == ["next"]:
        return cmd_next()
    if not os.environ.get("TMUX") or not os.environ.get("TMUX_PANE"):
        sys.exit(T["outside_tmux"])
    if not startup_dedupe():
        return
    os.environ.setdefault("ESCDELAY", "25")
    curses.wrapper(lambda scr: UI(scr).run())


if __name__ == "__main__":
    main()
