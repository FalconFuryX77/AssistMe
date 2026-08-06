# Architecture Notes

## Backend structure

- The API entrypoint is the FastAPI app in backend/app.py.
- Feature modules live under backend/api/ with separate folders for routers, schemas, and services.
- The health route currently serves as the first example of the intended layered structure.

## Next architecture tasks

1. Add authentication routers and schemas.
2. Introduce a database model layer.
3. Define shared response and error formats.
4. Create a simple deployment and environment configuration.
