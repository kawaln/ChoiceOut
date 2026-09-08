const { test, expect } = require("@playwright/test");

// A minimal stand-in for the real Google Maps JS SDK. The app only ever
// touches a handful of things from it (see pop.py's inline <script>):
// LatLng, PlacesServiceStatus.OK, and PlacesService.textSearch/getDetails.
// By intercepting the network request for the real SDK and handing back
// this fake instead, tests run instantly, offline, and never touch the
// real Google API quota.
const FAKE_MAPS_SDK = `
  window.google = {
    maps: {
      LatLng: function (lat, lng) {
        this.lat = () => lat;
        this.lng = () => lng;
      },
      places: {
        PlacesServiceStatus: { OK: "OK", ZERO_RESULTS: "ZERO_RESULTS" },
        PlacesService: function () {
          this.textSearch = function (request, callback) {
            callback(
              [
                {
                  name: "Test Pizza Place",
                  formatted_address: "123 Fake St, Testville",
                  place_id: "fake-place-1",
                  geometry: { location: { lat: () => 43.65, lng: () => -79.38 } },
                },
              ],
              "OK"
            );
          };
          this.getDetails = function (request, callback) {
            callback(
              {
                name: "Test Pizza Place",
                formatted_address: "123 Fake St, Testville",
                rating: 4.5,
                user_ratings_total: 200,
                formatted_phone_number: "(555) 123-4567",
                business_status: "OPERATIONAL",
                opening_hours: {
                  weekday_text: ["Monday: 9:00 AM – 9:00 PM"],
                  periods: [{ open: { day: 1, time: "0900" }, close: { day: 1, time: "2100" } }],
                  isOpen: () => true,
                },
              },
              "OK"
            );
          };
        },
      },
    },
  };
`;

// Same shape as FAKE_MAPS_SDK, but textSearch calls back with an EMPTY
// array instead of one fake place — this is the piece that actually makes
// a "zero results" scenario happen, since nothing about typing a
// particular search word changes what the fake SDK returns.
const EMPTY_RESULTS_MAPS_SDK = `
  window.google = {
    maps: {
      LatLng: function (lat, lng) {
        this.lat = () => lat;
        this.lng = () => lng;
      },
      places: {
        PlacesServiceStatus: { OK: "OK", ZERO_RESULTS: "ZERO_RESULTS" },
        PlacesService: function () {
          this.textSearch = function (request, callback) {
            callback([], "ZERO_RESULTS");
          };
          this.getDetails = function (request, callback) {
            callback(null, "NOT_FOUND");
          };
        },
      },
    },
  };
`;

test.describe("Nearby Eats", () => {
  test("homepage shows the hero heading", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator("h1")).toContainText("eat tonight");
  });

  test("shows the empty state when there are zero search results", async ({
    page,
    context,
  }) => {
    // Still needed: the app calls getCurrentPosition() before it does
    // anything else, so without this the test hangs waiting for a
    // permission prompt that never resolves.
    await context.grantPermissions(["geolocation"]);
    await context.setGeolocation({ latitude: 43.6532, longitude: -79.3832 });

    // FIX: use the EMPTY variant, not FAKE_MAPS_SDK — FAKE_MAPS_SDK always
    // calls back with one hardcoded place no matter what's searched, so it
    // can never produce a zero-results scenario.
    await page.route("**/maps.googleapis.com/maps/api/js**", (route) =>
      route.fulfill({ contentType: "application/javascript", body: EMPTY_RESULTS_MAPS_SDK })
    );

    await page.goto("/");
    await page.fill("#search", "NULL");
    await page.click("#searchBtn");

    // FIX: check the actual empty-state element (.empty), not <h1> (which
    // never changes), and check the real text the app renders — it never
    // displays the raw word "ZERO_RESULTS" anywhere.
    await expect(page.locator(".empty")).toContainText("Nothing nearby matched");
    await expect(page.locator(".card")).toHaveCount(0);
  });

  test("searching pizza renders a result card using mocked Places data", async ({
    page,
    context,
  }) => {
    // Fake the browser's location instead of relying on real GPS.
    await context.grantPermissions(["geolocation"]);
    await context.setGeolocation({ latitude: 43.6532, longitude: -79.3832 });

    // Swap the real Google Maps SDK for our fake one before the page loads it.
    await page.route("**/maps.googleapis.com/maps/api/js**", (route) =>
      route.fulfill({ contentType: "application/javascript", body: FAKE_MAPS_SDK })
    );

    await page.goto("/");
    await page.fill("#search", "pizza");
    await page.click("#searchBtn");

    const card = page.locator(".card").first();
    await expect(card.locator(".card-name")).toHaveText("Test Pizza Place");
    await expect(card.locator(".card-address")).toHaveText("123 Fake St, Testville");

    // Rating/phone come from the per-card getDetails call, which fires
    // shortly after the card itself is rendered.
    await expect(card.locator(".rating-score")).toHaveText("4.5");
    await expect(card.locator(".phone-box a")).toContainText("(555) 123-4567");
  });
});
