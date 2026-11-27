package com.gt5.halotile;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;

public class TileSyncReceiver extends BroadcastReceiver {
    @Override
    public void onReceive(Context context, Intent intent) {
        HaloBridge.requestTileRefresh(context);
    }
}
