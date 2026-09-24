# Run once after Fisher installs the plugins:
#   fish ~/.config/fish/setup-tide.fish
# This recreates selected Tide universal preferences without copying
# fish_variables, plugin caches, generated prompt caches, or machine paths.
set -U tide_left_prompt_items zmx pwd git newline character
set -U tide_right_prompt_items node bun go kubectl cmd_duration status context jobs time
set -U tide_zmx_bg_color normal
set -U tide_zmx_color normal
set -U tide_zmx_icon '󰆼'
set -U tide_character_color 5FD700
set -U tide_character_color_failure FF0000
set -U tide_character_icon '❯'
set -U tide_character_vi_icon_default '❮'
set -U tide_character_vi_icon_replace '▶'
set -U tide_character_vi_icon_visual V
set -U tide_git_truncation_length 24
set -U tide_pwd_color_anchors 00AFFF
set -U tide_pwd_color_dirs 0087AF
set -U tide_pwd_color_truncated_dirs 8787AF
set -U tide_prompt_add_newline_before false
set -U tide_prompt_color_frame_and_connection 6C6C6C
set -U tide_prompt_min_cols 34
set -U tide_prompt_pad_items false
set -U tide_prompt_transient_enabled true
set -U tide_status_color 5FAF00
set -U tide_status_color_failure D70000
set -U tide_status_icon '✔'
set -U tide_status_icon_failure '✘'
