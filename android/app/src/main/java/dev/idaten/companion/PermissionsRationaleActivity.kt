package dev.idaten.companion

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp

class PermissionsRationaleActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            MaterialTheme {
                Column(Modifier.fillMaxSize().padding(24.dp)) {
                    Text("Как Idaten использует Health Connect", style = MaterialTheme.typography.headlineSmall)
                    Text(
                        "Idaten читает выбранные вами данные о пробежках для ручной синхронизации с вашим личным аккаунтом. " +
                            "Новые активности остаются приватными. Маршрут запрашивается отдельно для конкретной тренировки.",
                    )
                }
            }
        }
    }
}
