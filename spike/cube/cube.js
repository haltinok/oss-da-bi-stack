// StarRocks speaks the MySQL protocol, so Cube uses its MySQL dialect, with one change.
//
// The stock dialect wraps every time column in CONVERT_TZ(col, @@session.time_zone, ...).
// That hides the column from StarRocks' partition pruning: each monthly
// pre-aggregation partition then scanned all 122 fact partitions instead of one
// (measured with EXPLAIN: partitions=122/122 vs 1/122). The mart stores UTC
// datetimes and Cube runs in UTC, so the conversion is an identity; leave the
// column bare. Phase 5 adds queryRewrite here.
const { MysqlQuery } = require('@cubejs-backend/schema-compiler/dist/src/adapter/MysqlQuery');

class StarRocksQuery extends MysqlQuery {
  convertTz(field) {
    return field;
  }

  timeStampCast(value) {
    return `CAST(${value} AS DATETIME)`;
  }
}

module.exports = {
  dialectFactory: () => StarRocksQuery,
};
