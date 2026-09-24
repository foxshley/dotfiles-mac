function _tide_item_zmx
    set -q ZMX_SESSION || return

    _tide_print_item zmx \
        $tide_zmx_icon' ' \
        $ZMX_SESSION
end
