package com.gt5.halotile;

import android.service.quicksettings.Tile;
import android.service.quicksettings.TileService;

public class HaloTileService extends TileService {

    @Override
    public void onTileAdded() {
        super.onTileAdded();
        HaloBridge.ensureFiles(this);
        refreshTile();
    }

    @Override
    public void onStartListening() {
        super.onStartListening();
        refreshTile();
    }

    @Override
    public void onClick() {
        super.onClick();
        HaloBridge.HaloState cur = HaloBridge.readState(this);
        boolean nextEnabled = !cur.enabled;
        HaloBridge.writeOptimisticState(this, nextEnabled, cur.mode, cur.brightness);
        applyToTile(nextEnabled, cur.mode, cur.brightness);
        HaloBridge.sendCommand(this, nextEnabled ? "on" : "off");
    }

    private void refreshTile() {
        HaloBridge.HaloState st = HaloBridge.readState(this);
        applyToTile(st.enabled, st.mode, st.brightness);
    }

    private void applyToTile(boolean enabled, String mode, int brightness) {
        Tile tile = getQsTile();
        if (tile == null) return;
        tile.setLabel(getString(R.string.tile_label));
        tile.setState(enabled ? Tile.STATE_ACTIVE : Tile.STATE_INACTIVE);
        tile.setSubtitle(enabled ? (HaloBridge.modeLabel(mode) + " · " + brightness + "%") : "已关闭");
        tile.updateTile();
    }
}
