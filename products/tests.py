from django.test import TestCase
from users.models import User, SellerProfile
from products.models import Product, ProductImage, ProductSpecification, Category
from django.db import IntegrityError


class ProductModelTest(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            username='seller',
            email='seller@test.com',
            password='pass1234',
            is_seller=True
        )

        self.seller = SellerProfile.objects.get(user=self.user)
        self.seller.is_verified = True
        self.seller.save()

        self.category = Category.objects.create(name="Electronics")

    def create_product(self):
        return Product.objects.create(
            seller=self.seller,
            category=self.category,
            name="Phone",
            description="Good phone",
            price=500,
            stock=10
        )

    def test_create_product(self):
        product = self.create_product()

        self.assertEqual(product.name, "Phone")
        self.assertEqual(product.seller, self.seller)
        self.assertEqual(product.category, self.category)
        self.assertTrue(product.is_available)

    def test_product_image(self):
        product = self.create_product()

        image = ProductImage.objects.create(
            product=product,
            image="test.jpg"
        )

        self.assertEqual(image.product, product)

    def test_product_specification(self):
        product = self.create_product()

        spec = ProductSpecification.objects.create(
            product=product,
            key="Size",
            value="55 inch"
        )

        self.assertEqual(spec.product, product)

    def test_unique_specification_key(self):
        product = self.create_product()

        ProductSpecification.objects.create(
            product=product,
            key="Color",
            value="Black"
        )

        # This will FAIL until we fix model constraint (see below)
        with self.assertRaises(IntegrityError):
            ProductSpecification.objects.create(
                product=product,
                key="Color",
                value="White"
            )


class CreateCategoryTest(TestCase):

    def test_create_category(self):
        category = Category.objects.create(name="Electronics")
        self.assertEqual(category.name, "Electronics")