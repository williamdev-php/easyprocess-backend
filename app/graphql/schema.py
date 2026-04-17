import strawberry
from strawberry.fastapi import GraphQLRouter

from app.auth.resolvers import Mutation as AuthMutation, Query as AuthQuery
from app.sites.resolvers import SiteMutation, SiteQuery


@strawberry.type
class Query(AuthQuery, SiteQuery):
    pass


@strawberry.type
class Mutation(AuthMutation, SiteMutation):
    pass


schema = strawberry.Schema(query=Query, mutation=Mutation)

graphql_app = GraphQLRouter(schema)
