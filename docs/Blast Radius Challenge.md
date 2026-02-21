# **Background**

In real-world software systems, even a small change can have wide-reaching consequences.

Adding a field to an API, modifying a validation rule, or refactoring a shared function can silently impact:

* Downstream services  
* Data flows  
* Business logic  
* Existing tests and assumptions

Today, engineers rely on experience, tribal knowledge, and manual inspection to estimate the **blast radius** of a change.

# **Problem Statement**

Your task is to build a system that, given:

1. An existing codebase (any one programming language), and  
2. A clearly specified code change (API change, behavior change, or structural modification),

can automatically **define the blast radius of that change** in a clear, explainable, and structured way.

The system should help an engineer answer:

"If I make this change, what parts of the system are impacted—and why?"

# **Core Requirements**

Your solution must:

### **1\. Model the Codebase**

* Parse the provided project  
* Identify key structural elements:  
  * Modules  
  * Classes  
  * Functions  
  * APIs  
* Capture relationships such as:  
  * Calls  
  * Dependencies  
  * Data flow  
* Represent this understanding as a **graph-based model**

This graph represents the **current reality** of the system.

### **2\. Accept Change Intent**

* Take a **structured description** of a change, for example:  
  * "Add an optional field to an API response"  
  * "Change validation logic for an input parameter"  
  * "Refactor a shared utility method"  
* The change intent will be explicit and unambiguous

### **3\. Analyze Blast Radius**

Using the graph, your system must:

* Identify **directly impacted components**  
* Identify **indirect or downstream impacts**  
* Classify impacts, for example:  
  * API-level  
  * Business logic  
  * Data handling  
  * Contract compatibility  
* Explain **why** each component is considered impacted

The output should make impact visible—not inferred.

# **Expected Output**

The system should produce a clear blast radius report, such as:

* Impacted APIs  
* Impacted modules or functions  
* Downstream dependencies  
* Areas of high risk or uncertainty  
* Known vs unknown impact zones

The output format is flexible (JSON, Markdown, CLI text), but it must be:

* Structured  
* Explainable  
* Engineer-readable

# **What You Do NOT Need to Build**

To keep the scope focused:

* No UI is required  
* No multi-language support  
* No project management or CI/CD integration

# **Evaluation Criteria**

Submissions will be evaluated on:

* **Accuracy** – Does the blast radius make technical sense?  
* **Completeness** – Are both direct and indirect impacts considered?  
* **Explainability** – Can an engineer understand **why** something is impacted?  
* **Graph Design** – Is the graph model appropriate and minimal?

# **Bonus (Optional)**

* Categorize impact severity (low / medium / high)  
* Highlight areas lacking sufficient information  
* Show traceability: change intent → impacted nodes  
* Detect potential contract-breaking changes

# **Expected Outcome**

By the end of this challenge, you should demonstrate that:

Given a proposed change, your system can make the blast radius explicit—before the change is merged.

This is not about predicting failures. It is about **making impact visible** so engineers can act with confidence.