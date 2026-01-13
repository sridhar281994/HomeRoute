package org.yourapp.billing

import android.app.Activity

object BillingBridge {

    lateinit var billingManager: BillingManager

    fun init(activity: Activity) {
        billingManager = BillingManager(activity) { purchase ->
            println("Purchase success: ${purchase.purchaseToken}")
        }

        billingManager.connect {}
    }

    fun buy(productId: String, activity: Activity) {
        billingManager.launchPurchase(activity, productId)
    }
}

