package com.mineopsdw.agent

import android.app.ActivityManager
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.os.BatteryManager
import android.os.PowerManager
import java.time.Instant

/**
 * Reference Kotlin collector for Phase 11 (Optional Android Companion Agent).
 * Collects battery level, temperature (only if exposed by BatteryManager),
 * memory usage, charging state, and battery saver state, sending authenticated
 * payloads to the PC backend (`POST /api/v1/android/telemetry`).
 */
data class AndroidTelemetrySample(
    val deviceId: String,
    val observedAtUtc: String,
    val batteryPercent: Double?,
    val batteryTempC: Double?,
    val ramUsedMib: Double?,
    val isCharging: Boolean?,
    val batterySaverActive: Boolean,
    val permissionDenied: Boolean = false
)

class MineOpsAndroidCollector(private val context: Context, private val deviceId: String) {

    fun collectSample(): AndroidTelemetrySample {
        val nowIso = Instant.now().toString()
        val powerManager = context.getSystemService(Context.POWER_SERVICE) as? PowerManager
        val batterySaver = powerManager?.isPowerSaveMode ?: false

        val intent = context.registerReceiver(null, IntentFilter(Intent.ACTION_BATTERY_CHANGED))
        val level = intent?.getIntExtra(BatteryManager.EXTRA_LEVEL, -1) ?: -1
        val scale = intent?.getIntExtra(BatteryManager.EXTRA_SCALE, -1) ?: -1
        val batteryPct = if (level >= 0 && scale > 0) (level * 100.0) / scale else null

        // EXTRA_TEMPERATURE is reported in tenths of a degree Celsius; never invent if missing
        val rawTempTenths = intent?.getIntExtra(BatteryManager.EXTRA_TEMPERATURE, Int.MIN_VALUE)
            ?: Int.MIN_VALUE
        val tempC = if (rawTempTenths > -200 && rawTempTenths < 1200) rawTempTenths / 10.0 else null

        val status = intent?.getIntExtra(BatteryManager.EXTRA_STATUS, -1) ?: -1
        val charging = if (status != -1) {
            status == BatteryManager.BATTERY_STATUS_CHARGING ||
                status == BatteryManager.BATTERY_STATUS_FULL
        } else null

        val actManager = context.getSystemService(Context.ACTIVITY_SERVICE) as? ActivityManager
        val memInfo = ActivityManager.MemoryInfo()
        actManager?.getMemoryInfo(memInfo)
        val ramUsedMib = if (memInfo.totalMem > 0) {
            (memInfo.totalMem - memInfo.availMem).toDouble() / (1024.0 * 1024.0)
        } else null

        return AndroidTelemetrySample(
            deviceId = deviceId,
            observedAtUtc = nowIso,
            batteryPercent = batteryPct,
            batteryTempC = tempC,
            ramUsedMib = ramUsedMib,
            isCharging = charging,
            batterySaverActive = batterySaver
        )
    }
}
