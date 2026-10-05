# Padua workshop groups

Registration, preferences, and group matching for the Padua AI research workshop.

## Architecture

- Static client on GitHub Pages: <https://bengolub-economics.github.io/padua-workshop-groups/>
- Firebase Authentication: email-link sign-in
- Private Cloud Firestore database in `europe-west1`; browser reads and writes are denied by rules
- Authenticated Python callable functions in `europe-west1`; organizer identity is `ben@bengolub.net`
- Google OR-Tools CP-SAT matching, followed by an independent validation pass

The public repository contains no participant data. The Firebase web configuration in `app.js` identifies the project; it is not a secret. Authorization is enforced in the callable functions and Firestore rules.

## Organizer flow

1. Sign in with `ben@bengolub.net`.
2. Open enrollment. Watch registrations and approve the real attendees.
3. Freeze the roster and open preferences. Participants each pick at least ten preferred people and any vetoes.
4. Close preferences, run matching, inspect hard-rule violations and access flags.
5. Publish one run. If the source hard rules are infeasible, the app requires an explicit acknowledgement of the proposed violations.
6. Download the organizer CSV/JSON export for backup.

The free-text reflection is visible only to the organizer and is excluded from automated matching. Participants see only their own assignment after publication.

## Deploy

The repository root is the GitHub Pages source on the `main` branch. The Firebase project ID is `padua-workshop-groups-2026`. The Cloud Firestore database and Authentication provider must be provisioned in Firebase. Deploy backend and rules with a current Firebase CLI:

```sh
firebase deploy --only firestore,functions --project padua-workshop-groups-2026
```

Keep the project's Cloud Run Functions spend cap and budget alerts active. Do not use real participant records for testing. Matching reference cases and tests are under `tests/`.
