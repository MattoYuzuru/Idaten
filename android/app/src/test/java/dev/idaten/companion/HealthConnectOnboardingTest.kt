package dev.idaten.companion

import android.content.Intent
import android.provider.Settings
import androidx.health.connect.client.HealthConnectClient
import dev.idaten.companion.health.HealthAvailabilityMapper
import dev.idaten.companion.health.HealthConnectExternalActions
import dev.idaten.companion.model.HealthAvailability
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class HealthConnectOnboardingTest {
    @Test
    fun mapsEverySdkAvailabilityState() {
        assertEquals(
            HealthAvailability.AVAILABLE,
            HealthAvailabilityMapper.fromSdkStatus(HealthConnectClient.SDK_AVAILABLE),
        )
        assertEquals(
            HealthAvailability.UPDATE_REQUIRED,
            HealthAvailabilityMapper.fromSdkStatus(HealthConnectClient.SDK_UNAVAILABLE_PROVIDER_UPDATE_REQUIRED),
        )
        assertEquals(
            HealthAvailability.UNAVAILABLE,
            HealthAvailabilityMapper.fromSdkStatus(HealthConnectClient.SDK_UNAVAILABLE),
        )
        assertEquals(HealthAvailability.UNAVAILABLE, HealthAvailabilityMapper.fromSdkStatus(Int.MIN_VALUE))
    }

    @Test
    fun androidNineToThirteenUsesPlayStoreWithHttpsFallback() {
        val candidates = HealthConnectExternalActions.candidates(33)
        assertEquals("market", candidates.first().uri?.substringBefore(":"))
        assertEquals("https", candidates.last().uri?.substringBefore(":"))

        val selected =
            HealthConnectExternalActions.firstResolvable(33) { action ->
                action.uri?.startsWith("https://") == true
            }
        assertEquals(candidates.last(), selected)
    }

    @Test
    fun androidFourteenUsesSystemSettingsPath() {
        val candidates = HealthConnectExternalActions.candidates(34)
        assertEquals(HealthConnectClient.ACTION_HEALTH_CONNECT_SETTINGS, candidates.first().action)
        assertEquals(Settings.ACTION_SETTINGS, candidates.last().action)
        assertNull(candidates.first().uri)
        assertEquals(candidates.last(), HealthConnectExternalActions.firstResolvable(34) { it.action == Settings.ACTION_SETTINGS })
    }

    @Test
    fun noHandlerProducesNoExternalAction() {
        assertNull(HealthConnectExternalActions.firstResolvable(33) { false })
        assertEquals(Intent.ACTION_VIEW, HealthConnectExternalActions.candidates(33).first().action)
    }
}
