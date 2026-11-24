# Connectors

Connectors bring information from other systems, such as an engineering or a logistics system, into chat. This page explains what they add to an answer and how to try them. Platform admins set connectors up and watch their health under [Connectors](ingestion.md#connectors).

## What connectors add to an answer

A connector works in one of two ways, or both:

- **Synced**: its content is copied into your documents and kept up to date. Answers cite it like any other document, and you can open it under [Documents](documents.md).
- **Live**: nothing is copied. When you ask a question, Knowcelium asks the connected system at that moment, which suits content that changes quickly, such as the status of a shipment. Answers cite it as a [source from a connected system](chat.md#sources-from-connected-systems) with a **Live** label.

Because both kinds are in the same chat, one question can use several systems, for example a change request from the engineering system and the delay of a shipment from the logistics system.

## Try the showcase

The showcase connects two made-up systems of an e-bike maker, Velora Mobility, an engineering system and a logistics system. Your administrator can start it; see the [showcase](../../examples/showcase/README.md) for how and for more questions. To try it:

1. Open **Connectors** and check that `showcase-engineering` and `showcase-logistics` are **Healthy**. A few minutes after the start they may still say **Not synced yet**; wait until they don't.
2. Open **Chat** and select **New chat**.
3. Ask: **Which open change requests affect parts whose supplier has a delayed shipment?**
4. While the answer is prepared, a list under the status line shows each system being searched. When it is done, the answer lists the engineering documents under **Sources** and the logistics system under **Connector sources**.
5. Open **Sources in this chat** in the header to see the connected systems the conversation has used so far.

Other questions that need both systems: **Which open change requests concern parts from our lowest-rated supplier, and why was the change requested?** (answered from synced documents) and **How many torque sensors are in stock and when does Sensora Precision deliver more?**

If a system doesn't answer in time, its entry in the list reads **unavailable**, and the answer is written from the other sources. Ask again in a moment.
