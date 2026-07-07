package dev.idaten.companion.health

import android.content.Intent
import android.net.Uri
import android.provider.Settings
import androidx.health.connect.client.HealthConnectClient
import dev.idaten.companion.model.HealthAvailability

enum class HealthOnboardingState {
    CHECKING,
    PROVIDER_UPDATE_REQUIRED,
    UNSUPPORTED,
    PERMISSIONS_REQUIRED,
    READY,
}

object HealthAvailabilityMapper {
    fun fromSdkStatus(status: Int): HealthAvailability =
        when (status) {
            HealthConnectClient.SDK_AVAILABLE -> HealthAvailability.AVAILABLE
            HealthConnectClient.SDK_UNAVAILABLE_PROVIDER_UPDATE_REQUIRED -> HealthAvailability.UPDATE_REQUIRED
            else -> HealthAvailability.UNAVAILABLE
        }
}

data class ExternalAction(
    val action: String,
    val uri: String? = null,
) {
    fun toIntent(): Intent = Intent(action, uri?.let(Uri::parse))
}

object HealthConnectExternalActions {
    private const val PROVIDER_PACKAGE = "com.google.android.apps.healthdata"

    fun candidates(sdkInt: Int): List<ExternalAction> =
        if (sdkInt >= 34) {
            listOf(
                ExternalAction(HealthConnectClient.ACTION_HEALTH_CONNECT_SETTINGS),
                ExternalAction(Settings.ACTION_SETTINGS),
            )
        } else {
            listOf(
                ExternalAction(Intent.ACTION_VIEW, "market://details?id=$PROVIDER_PACKAGE"),
                ExternalAction(
                    Intent.ACTION_VIEW,
                    "https://play.google.com/store/apps/details?id=$PROVIDER_PACKAGE",
                ),
            )
        }

    fun firstResolvable(
        sdkInt: Int,
        canResolve: (ExternalAction) -> Boolean,
    ): ExternalAction? = candidates(sdkInt).firstOrNull(canResolve)
}
