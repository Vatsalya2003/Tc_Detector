package demo.billing;

import com.launchdarkly.sdk.LDContext;
import com.launchdarkly.sdk.server.LDClient;
import io.getunleash.Unleash;

class InvoiceService {

    private final Unleash unleash;
    private final LDClient ldClient;

    InvoiceService(Unleash unleash, LDClient ldClient) {
        this.unleash = unleash;
        this.ldClient = ldClient;
    }

    String render(String customerId) {
        // POSITIVE C: generic isEnabled("x"), counted because Unleash is a dependency.
        if (unleash.isEnabled("new-invoice-layout")) {
            return "new";
        }
        LDContext context = LDContext.create(customerId);
        // POSITIVE C: LaunchDarkly-specific call.
        if (ldClient.boolVariation("invoice-discounts", context, false)) {
            return "discounted";
        }
        return "classic";
    }
}
