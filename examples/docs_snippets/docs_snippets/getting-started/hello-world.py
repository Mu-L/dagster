import dagster as dg


@dg.asset
def hello(context: dg.AssetExecutionContext):
    context.log.info("Hello!")


@dg.asset(deps=[hello])
def world(context: dg.AssetExecutionContext):
    context.log.info("World!")


if __name__ == "__main__":
    dg.materialize(hello)
    dg.materialize(world)
