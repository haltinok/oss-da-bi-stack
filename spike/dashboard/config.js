// Where the browser finds Keycloak, the auth service and Cube (all published on localhost).
window.SPIKE = {
  keycloak: { url: "http://localhost:8180", realm: "spike", clientId: "dashboard" },
  auth: "http://localhost:8200",
  cube: "http://localhost:4000/cubejs-api/v1",
};
