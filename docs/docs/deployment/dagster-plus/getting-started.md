---
description: Get started with Dagster+ by creating a Dagster+ organization and choosing the Serverless or Hybrid deployment type.
title: Getting started with Dagster+
sidebar_position: 100
---

To get started with Dagster+, you will need to create a Dagster+ organization and choose your deployment type (Serverless or Hybrid).

## Create a Dagster+ organization

First, [create a Dagster+ organization](https://dagster.plus/signup). You can sign up with:

- a Google email address
- a GitHub account
- a one-time email link (ideal if you are using a corporate email). You can set up SSO after completing these steps.

## Choose your deployment type

### Dagster+ Serverless

[Dagster+ Serverless](/deployment/dagster-plus/serverless) is the easiest way to get started and is a good options if you have limited DevOps support. In Dagster+ Serverless, your Dagster code is executed in Dagster+, so you will need to be comfortable sharing credentials with Dagster+ for the tools you want to orchestrate.

To get started with Dagster+ Serverless, follow the Dagster+ onboarding to add a new project. You will be guided through the steps to create a Git repository with your Dagster code and set up the necessary CI/CD actions to deploy that repository to Dagster+.

:::tip

If you don't have any Dagster code, you can select an example project or import an existing dbt project.

:::

### Dagster+ Hybrid

[Dagster+ Hybrid](/deployment/dagster-plus/hybrid) is a good choice if you want to orchestrate tools without giving Dagster+ direct access to your systems. Dagster+ Hybrid requires more DevOps support.

To get started with Dagster+ Hybrid, follow the steps in the [Dagster+ Hybrid documentation](/deployment/dagster-plus/hybrid) to install a Dagster+ Hybrid agent and set up CI/CD.

## Next steps

Your Dagster+ account is automatically enrolled in a trial. You can pick your plan type and enter your billing information, or [contact the Dagster team](https://dagster.io/contact) if you need support or want to evaluate the Dagster+ Pro plan.

If you are migrating from OSS to Dagster+, follow the steps in the [OSS to Dagster+ migration guide](/migration/oss-to-dagster-plus).
