package demo.catalog;

import dev.openfeature.sdk.Client;
import org.ff4j.FF4j;

class SearchService {

    private final Client client;
    private final FF4j ff4j;
    private final Account account;
    private final Validator validator;

    SearchService(Client client, FF4j ff4j, Account account, Validator validator) {
        this.client = client;
        this.ff4j = ff4j;
        this.account = account;
        this.validator = validator;
    }

    String search(String query) {
        // POSITIVE C: Togglz enum feature (library-specific, no dependency needed).
        if (CatalogFeatures.NEW_SEARCH.isActive()) {
            return "new";
        }
        // POSITIVE C: OpenFeature-specific call.
        if (client.getBooleanValue("fast-search", false)) {
            return "fast";
        }
        // POSITIVE C: FF4J-specific call.
        if (ff4j.check("bulk-import")) {
            return "bulk";
        }
        // NEGATIVE: an unrelated isEnabled() with no flag library dependency.
        if (account.isEnabled()) {
            return "account";
        }
        // NEGATIVE: an unrelated isEnabled("x") with no flag library dependency.
        if (validator.isEnabled("strict")) {
            return "strict";
        }
        return "plain";
    }
}
