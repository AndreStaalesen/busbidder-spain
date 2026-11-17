# Class diagrams

**Legend**
- Solid line with hollow triangle: inheritance (points to the parent class)
- Filled diamond: composition (the owner creates and holds the part)
- Hollow diamond: aggregation (the owner holds parts that exist on their own)
- Solid arrow: association (holds a reference to)
- Dashed arrow: dependency (uses or creates)
- «abstract»: abstract base class; methods in *italics* are abstract and must be implemented by subclasses
- «frozen»: frozen dataclass (cannot be changed after creation)

## 1. Main classes and how they work together

```mermaid
classDiagram
    direction TB

    class BusBidderApp {
        +search(request) SearchResult
    }
    class OfferValidator {
        +validate(records) ValidationReport
    }
    class ValidationReport {
        offers
        rejected
        corrected
        quarantined
    }
    class TravelRequest {
        <<frozen>>
        destination
        earliest_date
        latest_date
    }
    class TravellerProfile {
        <<frozen>>
        name
        departure_window
        weights
    }
    class Limits {
        <<frozen>>
        max_price_eur
        max_transfers
        max_duration_minutes
        changeable_required
        refundable_required
    }
    class OfferFilter {
        +apply(offers, request) FilterResult
    }
    class Constraint {
        <<abstract>>
        +check(offer, request) bool
    }
    class Ranker {
        +rank(offers, request) list
    }
    class Criterion {
        <<abstract>>
        +score(offer, context) float
    }
    class Explainer {
        +explain_all() list
    }
    class RankedOffer {
        rank
        total
        scores: score and weight per criterion
    }
    class Offer {
        offer_id
        departure
        arrival
        price_eur
        transfers
        seats_available
        co2_kg
        +duration_minutes
        +reserve_seat()
    }
    class Company {
        <<frozen>>
        code
        name
    }
    class Destination {
        <<frozen>>
        code
        name
        distance_km
    }
    class FareConditions {
        <<frozen>>
        changeable
        refundable
        luggage_bags
    }
    class BookingManager {
        +book(offer, name) Booking
    }
    class Booking {
        <<frozen>>
        reference
        traveller_name
        price_eur
        booked_at
    }

    BusBidderApp ..> OfferValidator : loads data with
    BusBidderApp ..> OfferFilter : uses
    BusBidderApp ..> Ranker : uses
    BusBidderApp ..> Explainer : uses
    BusBidderApp *-- BookingManager

    OfferValidator ..> ValidationReport : creates
    ValidationReport o-- Offer
    TravelRequest --> TravellerProfile
    TravellerProfile *-- Limits
    OfferFilter o-- Constraint
    Ranker *-- Criterion
    Ranker ..> RankedOffer : creates
    Explainer --> RankedOffer
    RankedOffer --> Offer
    Offer --> Company
    Offer --> Destination
    Offer *-- FareConditions
    BookingManager o-- Booking
    BookingManager ..> Offer : reserves seat
    Booking *-- FareConditions : copy at booking time
```

## 2. Constraint hierarchy (hard constraints)

```mermaid
classDiagram
    direction TB

    class Constraint {
        <<abstract>>
        name
        layer
        outcome
        +is_active(request) bool
        +check(offer, request)* bool
        +describe(request)* str
    }
    class MaximumConstraint {
        <<abstract>>
        +limit(request)*
        +value(offer)*
    }
    class RequiredFeatureConstraint {
        <<abstract>>
        +required(request)* bool
        +has_feature(offer)* bool
    }
    Constraint <|-- DestinationConstraint
    Constraint <|-- TravelWindowConstraint
    Constraint <|-- SeatsAvailableConstraint
    Constraint <|-- MaximumConstraint
    Constraint <|-- RequiredFeatureConstraint
    MaximumConstraint <|-- MaxBudgetConstraint
    MaximumConstraint <|-- MaxTransfersConstraint
    MaximumConstraint <|-- MaxDurationConstraint
    RequiredFeatureConstraint <|-- ChangeableRequiredConstraint
    RequiredFeatureConstraint <|-- RefundableRequiredConstraint

    note for Constraint "Layer A: Destination, TravelWindow, SeatsAvailable<br>Layer B: all subclasses of MaximumConstraint and RequiredFeatureConstraint"
```

## 3. Criterion hierarchy (scoring criteria)

```mermaid
classDiagram
    direction TB

    class Criterion {
        <<abstract>>
        name
        +score(offer, context)* float
    }
    class RatioCriterion {
        <<abstract>>
        +value(offer)*
        +score(offer, context) float
        +score_missing(offer, context) float
    }
    class EmissionsCriterion {
        +score_missing(offer, context) float
    }
    Criterion <|-- RatioCriterion
    Criterion <|-- DepartureCriterion
    Criterion <|-- FlexibilityCriterion
    RatioCriterion <|-- PriceCriterion
    RatioCriterion <|-- DurationCriterion
    RatioCriterion <|-- EmissionsCriterion

    note for Criterion "Each subclass is registered with @register_criterion(name)"
```
